"""Response quality evals for the LangGraph Human-in-the-Loop agent.

Validates that agent responses are coherent, structured, and substantive
for conversational queries that do not trigger tool use.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.plan_coherence import score_plan_coherence

pytestmark = pytest.mark.langgraph_hitl


async def test_plan_coherence(run_eval: Any, score_collector: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    result = await run_eval(
        "Explain what human-in-the-loop means in AI and why it is important"
    )
    assert result.success, f"Agent request failed: {result.error}"
    score = score_plan_coherence(result)
    score_collector.record(
        "Explain what human-in-the-loop means in AI and why it is important", score
    )
    assert score.passed, (
        f"Plan coherence check failed (score={score.value:.2f}): {score.details}"
    )
