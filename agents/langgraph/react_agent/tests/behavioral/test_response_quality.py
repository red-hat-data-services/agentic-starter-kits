"""Response quality evals for the LangGraph React agent.

Validates that agent responses are coherent, structured, and substantive.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.plan_coherence import score_plan_coherence

pytestmark = pytest.mark.langgraph_react


async def test_plan_coherence(run_eval: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    result = await run_eval(
        "Explain how to deploy a machine learning model on OpenShift"
    )
    assert result.success, f"Agent request failed: {result.error}"
    score = score_plan_coherence(result)
    assert score.passed, (
        f"Plan coherence check failed (score={score.value:.2f}): {score.details}"
    )
