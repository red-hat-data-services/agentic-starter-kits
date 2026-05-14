"""Response quality evals for the LangGraph Agentic RAG agent.

Validates that agent responses are coherent, structured, and substantive
when answering questions using retrieved context.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.plan_coherence import score_plan_coherence

pytestmark = pytest.mark.agentic_rag


async def test_plan_coherence(run_eval: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    result = await run_eval(
        "Explain how RAG works and what are its key components"
    )
    assert result.success, f"Agent request failed: {result.error}"
    score = score_plan_coherence(result)
    assert score.passed, (
        f"Plan coherence check failed (score={score.value:.2f}): {score.details}"
    )
