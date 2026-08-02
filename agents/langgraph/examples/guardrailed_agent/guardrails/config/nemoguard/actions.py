"""Custom topic-policy check action for models that speak the "custom policy" /
"User Safety: safe|unsafe" convention (e.g. nvidia/nemotron-3.5-content-safety),
instead of the strict "on-topic"/"off-topic" convention that NeMo Guardrails'
built-in `topic_safety_check_input` action expects from
nvidia/llama-3.1-nemoguard-8b-topic-control.

The topic policy itself isn't sent from here — it's baked into the
topic_control model's `parameters.chat_template_kwargs.custom_policy` in
config.yaml (see generate_config.py), which these NIM models apply
server-side. This action just forwards the raw user message and parses the
"User Safety: safe|unsafe" verdict out of the model's raw output, failing
closed (blocking) if that field can't be found.

Auto-loaded by NeMo Guardrails from this config directory; invoked via the
`topic policy check input $model` flow in topic_policy.co.
"""

import logging
import re
from typing import Dict, Optional

from langchain_core.language_models import BaseLLM
from nemoguardrails.actions.actions import action
from nemoguardrails.actions.llm.utils import llm_call
from nemoguardrails.context import llm_call_info_var
from nemoguardrails.logging.explain import LLMCallInfo

log = logging.getLogger(__name__)

TOPIC_POLICY_TEMPERATURE = 0.0
TOPIC_POLICY_MAX_TOKENS = 20

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

    messages = [{"type": "user", "content": user_input}]
    result = await llm_call(
        llm,
        messages,
        llm_params={
            "temperature": TOPIC_POLICY_TEMPERATURE,
            "max_tokens": TOPIC_POLICY_MAX_TOKENS,
        },
    )

    on_topic = _parse_user_safety_verdict(result)
    log.debug(
        "Topic policy check for %r -> %r (on_topic=%s)", user_input, result, on_topic
    )
    return {"on_topic": on_topic}
