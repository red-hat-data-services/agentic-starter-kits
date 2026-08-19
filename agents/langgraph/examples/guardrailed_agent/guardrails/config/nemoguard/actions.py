"""Custom topic-policy check action for models that speak the "custom policy" /
"User Safety: safe|unsafe" convention (e.g. nvidia/nemotron-3.5-content-safety),
instead of the strict "on-topic"/"off-topic" convention that NeMo Guardrails'
built-in `topic_safety_check_input` action expects from
nvidia/llama-3.1-nemoguard-8b-topic-control.

The banking topic policy is passed on every NIM call via
`chat_template_kwargs.custom_policy` (see generate_config.py). The same text is
also baked into config.yaml for documentation, but we forward it explicitly here
because some NIM client / NeMo Guardrails versions do not reliably apply model
parameters from config at LLM init time.

Auto-loaded by NeMo Guardrails from this config directory; invoked via the
`topic policy check input $model` flow in topic_policy.co.

This module stays LangChain-free so it loads on RHOAI NeMo 0.24 servers
that dropped LangChain, while still accepting 0.21 LangChain LLM objects
when those are injected into ``llms``.
"""

import logging
import os
import re
from typing import Any, Dict, Optional

from nemoguardrails.actions.actions import action
from nemoguardrails.actions.llm.utils import llm_call
from nemoguardrails.context import llm_call_info_var
from nemoguardrails.library.content_safety.actions import (
    content_safety_check_input as _library_content_safety_check_input,
)
from nemoguardrails.library.content_safety.actions import (
    content_safety_check_output as _library_content_safety_check_output,
)
from nemoguardrails.library.content_safety.actions import (
    content_safety_check_output_mapping,
)
from nemoguardrails.logging.explain import LLMCallInfo

log = logging.getLogger(__name__)

TOPIC_POLICY_TEMPERATURE = 0.0
TOPIC_POLICY_MAX_TOKENS = 20

# Keep in sync with generate_config._DEFAULT_TOPIC_CONTROL_POLICY.
_DEFAULT_TOPIC_POLICY = """The AI assistant is a customer service agent at a retail bank, helping customers with their banking needs only.
Allowed: account balances, transactions, and account history; billing, payments, and due dates; bank products, services, interest rates, and fees; branch locations, hours, and contact information; online banking, mobile app, and password resets; small talk and greetings.
Not allowed: medical or health advice; legal advice or legal proceedings; investment recommendations or stock picks; cooking, recipes, or food preparation; entertainment, sports, or celebrity gossip; personal relationships or dating advice; any other topic unrelated to banking and financial services."""

# Tolerates both plain-text ("User Safety: unsafe") and JSON-ish
# ('"User Safety": "unsafe"') verdict formats.
_VERDICT_PATTERN = re.compile(
    r"user\s+safety\"?\s*:\s*\"?(safe|unsafe)\b", re.IGNORECASE
)


def _parse_user_safety_verdict(result: str) -> bool:
    """Parse a "User Safety: safe|unsafe" verdict from the model's raw output.

    Returns True (on-topic, i.e. allow) only for an explicit "safe" match.
    Fails closed (blocks) on anything else — empty output, a garbled
    response, or a "User Safety" value the model didn't set to exactly
    "safe" — since this is a safety rail: silently letting unparseable
    classifier output through is worse than an occasional false block.
    """
    match = _VERDICT_PATTERN.search(result)
    if match is None:
        log.warning(
            "Topic policy check returned an unparseable verdict %r; failing "
            "closed (blocking).",
            result,
        )
        return False
    return match.group(1).lower() == "safe"


_ACCOUNT_ID_RE = re.compile(r"\bACCT-\d+\b", re.IGNORECASE)
# Keep in sync with rails.regex_detection in config.yaml.example (both profiles).
# Requires at least one of previous/above/your/the before instructions/rules/prompts
# so "Ignore your previous instructions ..." is caught, not only "Ignore previous ...".
_JAILBREAK_PHRASING_RE = re.compile(
    r"ignore\s+(all\s+)?(of\s+)?((your|the|previous|above)\s+)+"
    r"(instructions|rules|prompts)"
    r"|reveal your system prompt|\bsystem prompt\b",
    re.IGNORECASE,
)
_SENSITIVE_PII_RE = re.compile(
    r"\b(\d{3}-\d{2}-\d{4}|ssn|social security)\b"
    r"|\b(?:\d[ -]*?){13,19}\b"
    r"|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    r"|\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
    r"|\b\d{1,5}\s+\w+\s+(street|st|avenue|ave|road|rd|drive|dr|lane|ln|blvd)\b",
    re.IGNORECASE,
)


def _is_pii_or_privacy(violation: str) -> bool:
    return "pii" in violation or "privacy" in violation


def _is_output_demo_noise(violation: str) -> bool:
    """Categories the output classifier piggy-backs onto demo ACCT-* replies.

    Once S9 fires on an account id, the model often also dumps S3/S5/S13 on
    an otherwise valid balance disclosure. Input rails stay PII-only.
    """
    return _is_pii_or_privacy(violation) or any(
        token in violation
        for token in (
            "needs caution",
            "criminal planning",
            "controlled/regulated",
            "controlled substances",
        )
    )


def _allow_banking_account_pii(
    user_text: str, result: dict, *, for_output: bool = False
) -> dict:
    """Allow a demo account-id banking lookup through content-safety PII.

    The safety classifier treats identifiers such as ACCT-12345 as PII and
    would otherwise block the demo's legitimate balance queries. The carve-out
    requires an ``ACCT-<digits>`` id on the *user* turn (never the bot
    reply), rejects jailbreak phrasing, and still fails closed on SSNs,
    PANs, emails, phones, and addresses. Input rails require a PII/Privacy-only
    hit. Output rails also waive the S3/S5/S13 tags this classifier commonly
    attaches to a balance disclosure that repeats the user-supplied id.
    """
    if result.get("allowed", True):
        return result
    violations = [str(v).lower() for v in (result.get("policy_violations") or [])]
    if not violations:
        return result
    user_text = user_text or ""
    if _JAILBREAK_PHRASING_RE.search(user_text):
        return result
    if _SENSITIVE_PII_RE.search(user_text) or not _ACCOUNT_ID_RE.search(user_text):
        return result
    if for_output:
        if all(_is_output_demo_noise(v) for v in violations):
            log.info(
                "Allowing output-rail demo-account false positives on a banking lookup"
            )
            return {"allowed": True, "policy_violations": []}
        return result
    if all(_is_pii_or_privacy(v) for v in violations):
        log.info("Allowing content-safety PII/Privacy hit on a banking account lookup")
        return {"allowed": True, "policy_violations": []}
    return result


def _chat_template_from_mapping(source: Any) -> Optional[dict[str, Any]]:
    """Extract chat_template_kwargs from a model-kwargs mapping, if present."""
    if not isinstance(source, dict):
        return None
    kwargs = source.get("chat_template_kwargs")
    if isinstance(kwargs, dict) and kwargs.get("custom_policy"):
        return kwargs
    return None


def _resolve_chat_template_kwargs(llm: Any) -> dict[str, Any]:
    """Return chat_template_kwargs for custom-policy topic classifiers.

    NeMo 0.24's default (LangChain-free) OpenAIChatModel stores extra
    parameters on ``_default_kwargs``. 0.21 LangChain models use
    ``model_kwargs``; the 0.24 LangChain adapter exposes the wrapped model
    as ``raw_llm``.
    """
    for source in (
        getattr(llm, "_default_kwargs", None),
        getattr(llm, "model_kwargs", None),
        getattr(getattr(llm, "raw_llm", None), "model_kwargs", None),
    ):
        from_config = _chat_template_from_mapping(source)
        if from_config:
            return from_config

    explicit = os.environ.get("TOPIC_CONTROL_CUSTOM_POLICY")
    if explicit:
        return {"custom_policy": explicit, "enable_thinking": False}

    return {"custom_policy": _DEFAULT_TOPIC_POLICY, "enable_thinking": False}


def _llm_response_text(result: Any) -> str:
    """Normalize ``llm_call`` output across NeMo 0.21 (str) and 0.24 (LLMResponse)."""
    if result is None:
        return ""
    content = getattr(result, "content", result)
    if content is None:
        return ""
    return content if isinstance(content, str) else str(content)


@action()
async def topic_policy_check_input(
    llms: Dict[str, Any],
    model_name: Optional[str] = None,
    context: Optional[dict] = None,
    **kwargs,
) -> dict:
    user_input: str = (context or {}).get("user_message", "")
    model_name = model_name or (context or {}).get("model")

    if model_name is None:
        raise ValueError(
            "Model name is required for topic policy check, please provide it "
            "as an argument in config.yaml, e.g. "
            "topic policy check input $model=topic_control"
        )

    llm = llms.get(model_name)
    if llm is None:
        raise ValueError(
            f"Model '{model_name}' not found in the list of available models "
            "for topic policy check. Check config.yaml's models list."
        )

    llm_call_info_var.set(
        LLMCallInfo(task=f"topic_policy_check_input $model={model_name}")
    )

    llm_params: dict = {
        "temperature": TOPIC_POLICY_TEMPERATURE,
        "max_tokens": TOPIC_POLICY_MAX_TOKENS,
        "chat_template_kwargs": _resolve_chat_template_kwargs(llm),
    }

    messages = [{"role": "user", "content": user_input}]
    result = await llm_call(
        llm,
        messages,
        llm_params=llm_params,
    )
    verdict_text = _llm_response_text(result)

    on_topic = _parse_user_safety_verdict(verdict_text)
    log.debug(
        "Topic policy check for %r -> %r (on_topic=%s)",
        user_input,
        verdict_text,
        on_topic,
    )
    return {"on_topic": on_topic}


@action()
async def content_safety_check_input(
    llms: Dict[str, Any],
    llm_task_manager: Any,
    model_name: Optional[str] = None,
    context: Optional[dict] = None,
    model_caches: Optional[dict] = None,
    **kwargs,
) -> dict:
    result = await _library_content_safety_check_input(
        llms,
        llm_task_manager,
        model_name=model_name,
        context=context,
        model_caches=model_caches,
        **kwargs,
    )
    user_input = (context or {}).get("user_message", "")
    return _allow_banking_account_pii(user_input, result)


@action(output_mapping=content_safety_check_output_mapping)
async def content_safety_check_output(
    llms: Dict[str, Any],
    llm_task_manager: Any,
    model_name: Optional[str] = None,
    context: Optional[dict] = None,
    model_caches: Optional[dict] = None,
    **kwargs,
) -> dict:
    result = await _library_content_safety_check_output(
        llms,
        llm_task_manager,
        model_name=model_name,
        context=context,
        model_caches=model_caches,
        **kwargs,
    )
    user_input = (context or {}).get("user_message", "")
    return _allow_banking_account_pii(user_input, result, for_output=True)
