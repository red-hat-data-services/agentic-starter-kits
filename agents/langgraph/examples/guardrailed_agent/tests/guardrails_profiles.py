"""Builds a guardrails profile's runtime config.yaml for offline tests.

Copies ``guardrails/config/<profile>`` into a temp dir and runs
``generate_config.py`` on its ``config.yaml.example`` with fixed test env,
so tests never depend on a developer's generated (gitignored) config.yaml.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = AGENT_DIR / "guardrails" / "config"
_SCRIPT_PATH = AGENT_DIR / "guardrails" / "generate_config.py"

_spec = importlib.util.spec_from_file_location("generate_config", _SCRIPT_PATH)
generate_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_config)

GUARDRAILS_ENV_VARS = [
    f"{prefix}_{suffix}"
    for prefix in generate_config._ROLE_ENV_PREFIX.values()
    for suffix in ("MODEL_ID", "LLM_BASE_URL", "API_KEY", "MODEL_ENGINE")
] + [
    "MODEL_ID",
    "LLM_BASE_URL",
    "API_KEY",
    "TOPIC_CONTROL_CUSTOM_POLICY",
    "GUARDRAILS_TRACING_ENABLED",
]


def clear_guardrails_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every env var generate_config reads, so ambient shell values
    (e.g. from ``source .env``) can't leak into a generated config."""
    for var in GUARDRAILS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def build_profile(
    dest_root: Path,
    profile: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_id: str,
    base_url: str,
    **env: str,
) -> Path:
    """Copy ``profile`` under ``dest_root``, generate its config.yaml from the
    example template, and return the copied profile dir. Extra ``env`` (e.g.
    ``CONTENT_SAFETY_MODEL_ID``) is set before generating."""
    profile_dir = dest_root / profile
    shutil.copytree(CONFIG_DIR / profile, profile_dir)
    config_path = profile_dir / "config.yaml"
    shutil.copy(profile_dir / "config.yaml.example", config_path)

    monkeypatch.setenv("MODEL_ID", model_id)
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    monkeypatch.setenv("API_KEY", "not-needed")
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    generate_config.generate_config(str(config_path))
    return profile_dir
