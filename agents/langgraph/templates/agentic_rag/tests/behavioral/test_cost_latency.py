"""Latency evals for the LangGraph Agentic RAG agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml. RAG queries include vector search latency
so thresholds are set higher than simple search agents.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.latency import score_latency

pytestmark = pytest.mark.agentic_rag


async def test_latency_under_threshold(
    run_eval: Any, agentic_rag_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response latency must stay within the p95 threshold."""
    max_latency = agentic_rag_thresholds["max_latency_p95"]
    query = "What is RAG?"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    score_collector.record(query, score)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
