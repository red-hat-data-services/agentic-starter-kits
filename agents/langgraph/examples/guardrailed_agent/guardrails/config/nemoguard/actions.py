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
"""

import logging
import os
import re
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseLLM
from nemoguardrails.actions.actions import action
from nemoguardrails.actions.llm.utils import llm_call
from nemoguardrails.context import llm_call_info_var
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


def _resolve_chat_template_kwargs(llm: BaseLLM) -> dict[str, Any]:
    """Return chat_template_kwargs for custom-policy topic classifiers."""
    from_config = (getattr(llm, "model_kwargs", None) or {}).get("chat_template_kwargs")
    if isinstance(from_config, dict) and from_config.get("custom_policy"):
        return from_config

    explicit = os.environ.get("TOPIC_CONTROL_CUSTOM_POLICY")
    if explicit:
        return {"custom_policy": explicit, "enable_thinking": False}

    return {"custom_policy": _DEFAULT_TOPIC_POLICY, "enable_thinking": False}


@action()
async def topic_policy_check_input(
    llms: Dict[str, BaseLLM],
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

    messages = [{"type": "user", "content": user_input}]
    result = await llm_call(
        llm,
        messages,
        llm_params=llm_params,
    )

    on_topic = _parse_user_safety_verdict(result)
    log.debug(
        "Topic policy check for %r -> %r (on_topic=%s)", user_input, result, on_topic
    )
    return {"on_topic": on_topic}
