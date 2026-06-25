"""Latency evals for the CrewAI Websearch agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.latency import score_latency

pytestmark = pytest.mark.crewai_websearch


async def test_latency_under_threshold(
    run_eval: Any, crewai_websearch_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response latency must stay within the p95 threshold."""
    max_latency = crewai_websearch_thresholds["max_latency_p95"]
    query = "What is the best platform for hosting AI workloads?"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    score_collector.record(query, score)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
