#!/usr/bin/env python3
"""Generate guardrails/config/<profile>/config.yaml from config.yaml.example.

Two profiles live side by side under guardrails/config/:

  local     — self-check rails (self_check_input/output) on a single "main"
              model, pointed at Ollama by default. No dedicated safety models
              required; good for demoing the proxy pattern with zero extra setup.
  nemoguard — layered content_safety/topic_control rails, each backed by a
              purpose-built NemoGuard model (NVIDIA-hosted NIM today; can be
              repointed at an in-cluster KServe endpoint too).

Select a profile via `make guardrails-server-local` / `make guardrails-server-nemoguard`.

For the nemoguard profile, each model role (main, content_safety, topic_control)
can be pointed at a different model/endpoint/key/engine via ROLE-prefixed
environment variables. Any override left unset falls back to the shared
MODEL_ID / LLM_BASE_URL / API_KEY values (or, for engine, to whatever's
already in config.yaml.example), so single-model setups need no changes.

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

Caveat for the "main" role specifically (verified against
nemoguardrails==0.21.0's server/api.py): the NeMo Guardrails server itself
overrides the "main" model's id/engine on *every* request from the OpenAI
`model` field the client sends — and this agent always sends
`model=MODEL_ID`. So MAIN_MODEL_ID has no effect once real traffic is
flowing through the proxy; it only affects the model id baked into the
static config.yaml (relevant if something hits the guardrails server
directly with a model name matching that baked value). MAIN_LLM_BASE_URL
and MAIN_API_KEY still take effect, since NeMo's override never touches
`api_key` and only touches `base_url` via its own separate
MAIN_MODEL_BASE_URL env var (which we don't set). MAIN_MODEL_ENGINE also
takes effect, but only because NeMo Guardrails' server happens to read
that exact env var name itself for the same purpose — not because this
script wires it through.

Invoked by `make guardrails-server-{local,nemoguard}` after the profile's
config.yaml.example has been copied to config.yaml.
"""

import argparse
import os

import yaml

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

# Deliberately duplicates (in a different format) the banking policy baked
# into nemoguard/prompts.yml's `topic_safety_check_input` prompt: that prompt
# feeds the built-in on-topic/off-topic flow via a fixed template, while this
# one is injected as chat_template_kwargs.custom_policy for custom-policy
# models. Keep both in sync if the banking policy scope changes.
_DEFAULT_TOPIC_CONTROL_POLICY = """The AI assistant is a customer service agent at a retail bank, helping customers with their banking needs only.
Allowed: account balances, transactions, and account history; billing, payments, and due dates; bank products, services, interest rates, and fees; branch locations, hours, and contact information; online banking, mobile app, and password resets; small talk and greetings.
Not allowed: medical or health advice; legal advice or legal proceedings; investment recommendations or stock picks; cooking, recipes, or food preparation; entertainment, sports, or celebrity gossip; personal relationships or dating advice; any other topic unrelated to banking and financial services."""

_BUILTIN_TOPIC_FLOW = "topic safety check input $model=topic_control"
_CUSTOM_POLICY_TOPIC_FLOW = "topic policy check input $model=topic_control"


def _role_override(role: str, suffix: str, default: str) -> str:
    """Look up a ROLE_SUFFIX env var override (e.g. MAIN_LLM_BASE_URL,
    TOPIC_CONTROL_MODEL_ENGINE), falling back to default if unset."""
    prefix = _ROLE_ENV_PREFIX.get(role)
    if prefix:
        override = os.environ.get(f"{prefix}_{suffix}")
        if override:
            return override
    return default


def _role_override_optional(role: str, suffix: str) -> str | None:
    """Return a ROLE_SUFFIX env var override, or None if unset."""
    prefix = _ROLE_ENV_PREFIX.get(role)
    if prefix:
        return os.environ.get(f"{prefix}_{suffix}") or None
    return None


def _topic_control_custom_policy(model_id: str) -> str | None:
    """Return the custom policy text to use for topic_control, or None to
    keep the built-in on-topic/off-topic flow.

    There's no opt-out for the auto-detection: if TOPIC_CONTROL_MODEL_ID
    matches a _CUSTOM_POLICY_MODEL_MARKERS substring, custom-policy mode
    always activates. If you need a known-custom-policy model to use the
    built-in flow instead, rename/fork it under a non-matching model id.
    """
    explicit = os.environ.get("TOPIC_CONTROL_CUSTOM_POLICY")
    if explicit:
        return explicit
    if any(marker in model_id.lower() for marker in _CUSTOM_POLICY_MODEL_MARKERS):
        return _DEFAULT_TOPIC_CONTROL_POLICY
    return None


def _tracing_enabled() -> bool:
    """Return True only when GUARDRAILS_TRACING_ENABLED is exactly ``true``.

    Matches the Makefile server targets (``= "true"``). ``1`` / ``yes`` / ``TRUE``
    do not enable tracing.
    """
    return os.environ.get("GUARDRAILS_TRACING_ENABLED", "") == "true"


def _apply_tracing_override(config: dict) -> bool:
    """Flip config['tracing']['enabled'] on when GUARDRAILS_TRACING_ENABLED is
    exactly ``true``. Off by default. Always forces enable_content_capture off.

    config.yaml.example already ships the full tracing block (adapters,
    span_format, enable_content_capture), so this is a boolean flip plus a
    safety pin — no schema surprises. Returns the resolved enabled state. If
    the config has no tracing block at all (older template), this is a no-op
    returning False.
    """
    tracing = config.get("tracing")
    if not isinstance(tracing, dict):
        return False
    enabled = _tracing_enabled()
    tracing["enabled"] = enabled
    tracing["enable_content_capture"] = False
    return enabled


def generate_config(config_path: str, *, omit_nim_api_keys: bool = False) -> list[str]:
    """Rewrite config_path in place with env-driven model overrides applied.

    config_path must already exist (i.e. config.yaml.example copied to
    config.yaml) and contain a `models` list with `type`/`engine`/`model`/
    `parameters` per NeMo Guardrails' config schema. Returns a human-readable
    summary of what was applied, one line per model role.

    When omit_nim_api_keys is True, api_key is omitted from every model role so
    cluster ConfigMaps do not embed secrets; runtime auth uses the
    NemoGuardrails CR env (OPENAI_API_KEY / NVIDIA_API_KEY) instead.
    """
    default_model = os.environ.get("MODEL_ID") or "llama3.1:8b"
    default_base_url = os.environ.get("LLM_BASE_URL") or "http://localhost:11434/v1"
    default_api_key = os.environ.get("API_KEY") or "not-needed"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if "models" not in config:
        raise ValueError(f"Malformed {config_path}: missing top-level 'models' list")

    summary = []
    use_custom_topic_flow = False
    for index, model in enumerate(config["models"]):
        role = model.get("type")
        if role is None:
            raise ValueError(
                f"Malformed {config_path}: models[{index}] is missing 'type'"
            )
        if "parameters" not in model:
            raise ValueError(
                f"Malformed {config_path}: models[{index}] (role={role!r}) is "
                "missing 'parameters'"
            )

        model_id = _role_override(role, "MODEL_ID", default_model)
        engine = _role_override(role, "MODEL_ENGINE", model.get("engine", "openai"))
        explicit_base_url = _role_override_optional(role, "LLM_BASE_URL")

        if engine == "nim":
            # NIM classifiers use NVIDIA's hosted endpoint by default — do not
            # inherit the main LLM's base_url (e.g. in-cluster vLLM).
            base_url = explicit_base_url
            api_key = (
                _role_override_optional(role, "API_KEY")
                or os.environ.get("NVIDIA_API_KEY")
                or default_api_key
            )
        else:
            base_url = (
                explicit_base_url if explicit_base_url is not None else default_base_url
            )
            api_key = _role_override(role, "API_KEY", default_api_key)

        model["model"] = model_id
        model["engine"] = engine
        if omit_nim_api_keys:
            # Cluster ConfigMaps must not embed secrets. Runtime auth uses the
            # NemoGuardrails CR env (OPENAI_API_KEY / NVIDIA_API_KEY).
            model["parameters"].pop("api_key", None)
            model["api_key_env_var"] = (
                "NVIDIA_API_KEY" if engine == "nim" else "OPENAI_API_KEY"
            )
        else:
            model.pop("api_key_env_var", None)
            model["parameters"]["api_key"] = api_key
        if base_url is not None:
            model["parameters"]["base_url"] = base_url
        else:
            model["parameters"].pop("base_url", None)

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

        endpoint = base_url if base_url is not None else "NIM default"
        summary.append(f"{role}={model_id}@{endpoint} (engine={engine}{extra})")

    if use_custom_topic_flow:
        rails = config.get("rails")
        if not isinstance(rails, dict):
            raise ValueError(
                f"Malformed {config_path}: missing top-level 'rails' mapping"
            )
        input_rails = rails.get("input")
        if not isinstance(input_rails, dict) or "flows" not in input_rails:
            raise ValueError(f"Malformed {config_path}: missing rails.input.flows list")
        input_flows = input_rails["flows"]
        if _BUILTIN_TOPIC_FLOW not in input_flows:
            raise ValueError(
                f"Malformed {config_path}: topic_control resolved to custom-policy "
                f"mode, but the expected flow {_BUILTIN_TOPIC_FLOW!r} was not found "
                f"in rails.input.flows ({input_flows!r}) to swap out for "
                f"{_CUSTOM_POLICY_TOPIC_FLOW!r}. Add the custom-policy flow to "
                "rails.input.flows yourself, or restore the built-in flow entry."
            )
        config["rails"]["input"]["flows"] = [
            _CUSTOM_POLICY_TOPIC_FLOW if f == _BUILTIN_TOPIC_FLOW else f
            for f in input_flows
        ]
        summary.append(
            "topic_control flow -> topic policy check input (custom policy mode)"
        )

    tracing_enabled = _apply_tracing_override(config)
    summary.append(
        "tracing=opentelemetry (per-rail spans, content capture disabled)"
        if tracing_enabled
        else "tracing=disabled (default)"
    )

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return summary


_PROFILE_CHOICES = ("local", "nemoguard")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        required=True,
        choices=sorted(_PROFILE_CHOICES),
        help="Guardrails profile to generate config.yaml for",
    )
    args = parser.parse_args()

    config_path = f"guardrails/config/{args.profile}/config.yaml"
    summary = generate_config(config_path)
    print(f"Config generated ({args.profile} profile):\n  " + "\n  ".join(summary))


if __name__ == "__main__":
    main()
