"""Fixtures for API contract tests.

These tests are agent-agnostic — they verify the FastAPI
application contract that all agents in agentic-starter-kits share.
Set AGENT_URL to target any deployed agent.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def agent_url() -> str:
    url = os.environ.get("AGENT_URL")
    if not url:
        pytest.fail(
            "AGENT_URL env var is required for API contract tests. "
            "Set it to the base URL of a running agent."
        )
    return url
