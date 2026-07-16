"""Response quality evals for the LangGraph DB Memory agent.

Validates that agent responses are coherent, structured, and substantive.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.plan_coherence import score_plan_coherence

pytestmark = pytest.mark.langgraph_db_memory


async def test_plan_coherence(run_eval: Any, score_collector: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    query = "Explain how to deploy a machine learning model on OpenShift"
    result = await run_eval(query, timeout_seconds=60.0)
    assert result.success, f"Agent request failed: {result.error}"
    score = score_plan_coherence(result)
    score_collector.record(query, score)
    assert score.passed, (
        f"Plan coherence check failed (score={score.value:.2f}): {score.details}"
    )
