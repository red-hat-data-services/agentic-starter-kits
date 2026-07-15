"""Shared fixtures for harness tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def langflow_run_response() -> dict:
    """Load the captured Langflow /api/v1/run response fixture."""
    return json.loads((FIXTURES_DIR / "langflow_run_response.json").read_text())
