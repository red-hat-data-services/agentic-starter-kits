"""Tests for agent graph construction helpers."""

from __future__ import annotations

import pytest
from ci_failure_summarizer.agent import get_graph_closure


def test_get_graph_closure_requires_model_id(monkeypatch):
    monkeypatch.delenv("MODEL_ID", raising=False)

    with pytest.raises(ValueError, match="MODEL_ID is required"):
        get_graph_closure(
            model_id=None,
            base_url="http://localhost:8080/v1",
            api_key="test-key",
        )
