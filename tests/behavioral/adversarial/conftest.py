"""Shared fixtures for adversarial tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

_PAYLOAD_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "adversarial"
    / "injection_payloads.yaml"
)


def load_injection_payloads() -> dict[str, list[dict[str, str]]]:
    """Load injection payloads from fixtures/adversarial/injection_payloads.yaml."""
    with open(_PAYLOAD_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def payloads_by_category(category: str) -> list[dict[str, str]]:
    """Return payloads for a single category, for use with pytest.mark.parametrize."""
    return load_injection_payloads().get(category, [])


@pytest.fixture
def target_agent_url() -> str:
    """Agent base URL from AGENT_URL env var or default localhost:8000."""
    return os.environ.get("AGENT_URL", "http://localhost:8000")


@pytest.fixture
def agent_url(target_agent_url: str) -> str:
    """Override root conftest agent_url to use target_agent_url."""
    return target_agent_url


@pytest.fixture
def injection_payloads() -> dict[str, list[dict[str, str]]]:
    """All injection payloads keyed by category."""
    return load_injection_payloads()
