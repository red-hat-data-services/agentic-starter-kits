"""Latency evals for the LangGraph React agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.latency import score_latency

pytestmark = pytest.mark.langgraph_react


async def test_latency_under_threshold(
    run_eval: Any, react_thresholds: dict[str, Any]
) -> None:
    """Response latency must stay within the p95 threshold."""
    max_latency = react_thresholds["max_latency_p95"]
    result = await run_eval("What is Red Hat OpenShift AI?")
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
