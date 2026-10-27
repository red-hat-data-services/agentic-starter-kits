"""Smoke tests that both guardrails profiles actually load through NeMo
Guardrails' own machinery (RailsConfig.from_path + LLMRails), not just that
their YAML is well-formed.

This catches things structural YAML checks can't: bad rails/action
wiring, prompts.yml schema mismatches, missing custom actions, etc. No LLM
calls are made — only config parsing and rails compilation are exercised.

Requires the `guardrails` extra (`uv run --extra guardrails pytest ...`);
skipped automatically if nemoguardrails isn't installed.
"""

import pytest
import yaml
from guardrails_profiles import build_profile, clear_guardrails_env

nemoguardrails = pytest.importorskip("nemoguardrails")
from nemoguardrails import LLMRails, RailsConfig  # noqa: E402

PROFILES = ("local", "nemoguard")


@pytest.fixture(autouse=True)
def _clean_guardrails_env(monkeypatch):
    clear_guardrails_env(monkeypatch)


@pytest.fixture()
def built_profile_dir(tmp_path, monkeypatch):
    """Returns a builder: profile name -> tmp profile dir with a generated
    config.yaml (fixed local-Ollama test env)."""

    def _build(profile: str):
        return build_profile(
            tmp_path,
            profile,
            monkeypatch,
            model_id="llama3.1:8b",
            base_url="http://localhost:11434/v1",
        )

    return _build


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_loads_via_rails_config(built_profile_dir, profile):
    """RailsConfig.from_path should parse the generated config.yaml,
    prompts.yml, and rails.co without raising."""
    profile_dir = built_profile_dir(profile)
    config = RailsConfig.from_path(str(profile_dir))
    assert config is not None


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_instantiates_llm_rails(built_profile_dir, profile):
    """LLMRails should instantiate cleanly, proving the rails/flows/actions
    wiring (including topic_policy.co's custom action for nemoguard) is
    valid and loadable — not just that the YAML parses."""
    profile_dir = built_profile_dir(profile)
    config = RailsConfig.from_path(str(profile_dir))
    rails = LLMRails(config=config, verbose=False)
    assert rails is not None


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(
    ("tracing_env", "expected"),
    [(None, False), ("true", True)],
)
def test_tracing_flag_flips_generated_config(
    built_profile_dir, monkeypatch, profile, tracing_env, expected
):
    """generate_config flips tracing.enabled from GUARDRAILS_TRACING_ENABLED,
    and NeMo Guardrails accepts the resulting config either way. Content capture
    stays off in both modes so no prompts/outputs land in span attributes."""
    if tracing_env is not None:
        monkeypatch.setenv("GUARDRAILS_TRACING_ENABLED", tracing_env)
    profile_dir = built_profile_dir(profile)

    generated = yaml.safe_load(
        (profile_dir / "config.yaml").read_text(encoding="utf-8")
    )
    assert generated["tracing"]["enabled"] is expected
    assert generated["tracing"]["enable_content_capture"] is False

    # NeMo's own loader must accept the config regardless of tracing state.
    config = RailsConfig.from_path(str(profile_dir))
    assert config.tracing.enabled is expected
