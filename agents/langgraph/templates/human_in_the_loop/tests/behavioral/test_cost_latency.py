"""Latency evals for the LangGraph Human-in-the-Loop agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.latency import score_latency

pytestmark = pytest.mark.langgraph_hitl


async def test_latency_under_threshold(
    run_eval: Any, hitl_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response latency must stay within the p95 threshold."""
    max_latency = hitl_thresholds["max_latency_p95"]
    result = await run_eval("Hello, how are you?")
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    score_collector.record("Hello, how are you?", score)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
