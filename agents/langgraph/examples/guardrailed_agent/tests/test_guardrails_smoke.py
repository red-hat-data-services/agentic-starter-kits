"""Smoke tests that both guardrails profiles actually load through NeMo
Guardrails' own machinery (RailsConfig.from_path + LLMRails), not just that
their YAML is well-formed.

This catches things structural YAML checks can't: bad rails/action
wiring, prompts.yml schema mismatches, missing custom actions, etc. No LLM
calls are made — only config parsing and rails compilation are exercised.

Requires the `guardrails` extra (`uv run --extra guardrails pytest ...`);
skipped automatically if nemoguardrails isn't installed.
"""

import importlib.util
import shutil
from pathlib import Path

import pytest

nemoguardrails = pytest.importorskip("nemoguardrails")
from nemoguardrails import LLMRails, RailsConfig  # noqa: E402

AGENT_DIR = Path(__file__).resolve().parents[1]
GUARDRAILS_DIR = AGENT_DIR / "guardrails"
CONFIG_DIR = GUARDRAILS_DIR / "config"
SCRIPT_PATH = GUARDRAILS_DIR / "generate_config.py"
PROFILES = ("local", "nemoguard")


def _load_generate_config_module():
    spec = importlib.util.spec_from_file_location("generate_config", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_config = _load_generate_config_module()

_ROLE_ENV_VARS = [
    f"{prefix}_{suffix}"
    for prefix in generate_config._ROLE_ENV_PREFIX.values()
    for suffix in ("MODEL_ID", "LLM_BASE_URL", "API_KEY", "MODEL_ENGINE")
]


@pytest.fixture(autouse=True)
def _clean_guardrails_env(monkeypatch):
    for var in _ROLE_ENV_VARS + [
        "MODEL_ID",
        "LLM_BASE_URL",
        "API_KEY",
        "TOPIC_CONTROL_CUSTOM_POLICY",
    ]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def built_profile_dir(tmp_path, monkeypatch):
    """Copies a profile dir to tmp, generates config.yaml from the example
    template with fixed test env, and returns the tmp profile dir path."""

    def _build(profile: str) -> Path:
        src_dir = CONFIG_DIR / profile
        dst_dir = tmp_path / profile
        shutil.copytree(src_dir, dst_dir)

        config_path = dst_dir / "config.yaml"
        shutil.copy(dst_dir / "config.yaml.example", config_path)

        monkeypatch.setenv("MODEL_ID", "llama3.1:8b")
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("API_KEY", "not-needed")
        generate_config.generate_config(str(config_path))
        return dst_dir

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
