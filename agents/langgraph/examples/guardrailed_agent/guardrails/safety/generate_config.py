#!/usr/bin/env python3
"""Generate guardrails/safety/config.yaml from config.yaml.example.

Each model role (main, content_safety, topic_control) can be pointed at a
different model/endpoint/key/engine via ROLE-prefixed environment variables.
Any override left unset falls back to the shared MODEL_ID / LLM_BASE_URL /
API_KEY values (or, for engine, to whatever's already in config.yaml.example),
so single-model setups need no changes.

    MAIN_MODEL_ID            MAIN_LLM_BASE_URL            MAIN_API_KEY            MAIN_MODEL_ENGINE
    CONTENT_SAFETY_MODEL_ID  CONTENT_SAFETY_LLM_BASE_URL  CONTENT_SAFETY_API_KEY  CONTENT_SAFETY_MODEL_ENGINE
    TOPIC_CONTROL_MODEL_ID   TOPIC_CONTROL_LLM_BASE_URL   TOPIC_CONTROL_API_KEY   TOPIC_CONTROL_MODEL_ENGINE

Setting a role's engine to "nim" routes that role through NeMo Guardrails'
NIM/ChatNVIDIA integration (requires the `langchain-nvidia-ai-endpoints`
package) instead of the generic OpenAI-compatible client. This matters for
NVIDIA's purpose-built NemoGuard NIM models (e.g.
nvidia/llama-3.1-nemoguard-8b-content-safety), which NVIDIA's own docs
integrate via engine=nim.

topic_control also supports a "custom policy" mode for models that classify
against a free-text policy (passed via chat_template_kwargs) rather than
NeMo Guardrails' built-in on-topic/off-topic prompt — e.g.
nvidia/nemotron-3.5-content-safety, the working successor to NVIDIA's
dedicated (currently broken) topic-control NIM. This is auto-enabled when
TOPIC_CONTROL_MODEL_ID matches a known custom-policy model, or forced via
TOPIC_CONTROL_CUSTOM_POLICY (free text). When active, the generated
config.yaml is rewired to use the `topic policy check input` flow
(topic_policy.co / actions.py) instead of the built-in one.

Invoked by `make guardrails-server` after config.yaml.example has been
copied to config.yaml.
"""

import os

import yaml

CONFIG_PATH = "guardrails/safety/config.yaml"

_ROLE_ENV_PREFIX = {
    "main": "MAIN",
    "content_safety": "CONTENT_SAFETY",
    "topic_control": "TOPIC_CONTROL",
}

# Models known to classify against a free-text "custom policy" (via
# chat_template_kwargs) rather than a fixed prompt template, returning a
# "User Safety: safe|unsafe" verdict. Matched as a substring of the resolved
# topic_control model id.
_CUSTOM_POLICY_MODEL_MARKERS = (
    "nemotron-3.5-content-safety",
    "nemotron-content-safety-reasoning",
)

_DEFAULT_TOPIC_CONTROL_POLICY = """The AI assistant is a customer service agent at a retail bank, helping customers with their banking needs only.
Allowed: account balances, transactions, and account history; billing, payments, and due dates; bank products, services, interest rates, and fees; branch locations, hours, and contact information; online banking, mobile app, and password resets; small talk and greetings.
Not allowed: medical or health advice; legal advice or legal proceedings; investment recommendations or stock picks; cooking, recipes, or food preparation; entertainment, sports, or celebrity gossip; personal relationships or dating advice; any other topic unrelated to banking and financial services."""

_BUILTIN_TOPIC_FLOW = "topic safety check input $model=topic_control"
_CUSTOM_POLICY_TOPIC_FLOW = "topic policy check input $model=topic_control"


def _role_override(role: str, suffix: str, default: str) -> str:
    prefix = _ROLE_ENV_PREFIX.get(role)
    if prefix:
        override = os.environ.get(f"{prefix}_{suffix}")
        if override:
            return override
    return default


def _role_engine_override(role: str, default: str) -> str:
    prefix = _ROLE_ENV_PREFIX.get(role)
    if prefix:
        override = os.environ.get(f"{prefix}_MODEL_ENGINE")
        if override:
            return override
    return default


def _topic_control_custom_policy(model_id: str) -> str | None:
    """Return the custom policy text to use for topic_control, or None to
    keep the built-in on-topic/off-topic flow."""
    explicit = os.environ.get("TOPIC_CONTROL_CUSTOM_POLICY")
    if explicit:
        return explicit
    if any(marker in model_id.lower() for marker in _CUSTOM_POLICY_MODEL_MARKERS):
        return _DEFAULT_TOPIC_CONTROL_POLICY
    return None


def main() -> None:
    default_model = os.environ.get("MODEL_ID") or "llama3.1:8b"
    default_base_url = os.environ.get("LLM_BASE_URL") or "http://localhost:11434/v1"
    default_api_key = os.environ.get("API_KEY") or "not-needed"

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    summary = []
    use_custom_topic_flow = False
    for model in config["models"]:
        role = model["type"]
        model_id = _role_override(role, "MODEL_ID", default_model)
        base_url = _role_override(role, "LLM_BASE_URL", default_base_url)
        api_key = _role_override(role, "API_KEY", default_api_key)
        engine = _role_engine_override(role, model.get("engine", "openai"))

        model["model"] = model_id
        model["engine"] = engine
        model["parameters"].update(base_url=base_url, api_key=api_key)

        extra = ""
        if role == "topic_control":
            policy = _topic_control_custom_policy(model_id)
            if policy:
                model["parameters"]["chat_template_kwargs"] = {
                    "custom_policy": policy,
                    "enable_thinking": False,
                }
                use_custom_topic_flow = True
                extra = ", custom_policy"

        summary.append(f"{role}={model_id}@{base_url} (engine={engine}{extra})")

    if use_custom_topic_flow:
        input_flows = config["rails"]["input"]["flows"]
        config["rails"]["input"]["flows"] = [
            _CUSTOM_POLICY_TOPIC_FLOW if f == _BUILTIN_TOPIC_FLOW else f
            for f in input_flows
        ]
        summary.append(
            "topic_control flow -> topic policy check input (custom policy mode)"
        )

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print("Config generated:\n  " + "\n  ".join(summary))


if __name__ == "__main__":
    main()
