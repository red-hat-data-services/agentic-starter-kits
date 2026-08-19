"""Response quality evals for the LangGraph Guardrailed agent."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import assert_not_graceful_degrade, load_golden
from harness.scorers.plan_coherence import score_completeness, score_plan_coherence

pytestmark = pytest.mark.langgraph_guardrailed


def _queries_with_expected_elements() -> list[dict[str, Any]]:
    """Return golden queries whose expected elements should appear in the reply."""
    return [
        q
        for q in load_golden()
        if q.get("expected_elements")
        and q.get("category")
        not in {"guardrails_blocked", "adversarial", "guardrails_injection"}
    ]


async def test_plan_coherence(run_eval: Any, score_collector: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    query = "Explain how checking and savings accounts differ for everyday banking"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"
    assert_not_graceful_degrade(result)
    score = score_plan_coherence(result)
    score_collector.record(query, score)
    assert score.passed, (
        f"Plan coherence check failed (score={score.value:.2f}): {score.details}"
    )


@pytest.mark.parametrize(
    "golden",
    _queries_with_expected_elements(),
    ids=lambda q: q["query"][:60],
)
async def test_response_completeness(
    run_eval: Any, golden: dict[str, Any], score_collector: Any
) -> None:
    """Response should contain all expected elements from the golden dataset."""
    result = await run_eval(
        golden["query"],
        expected_tools=golden.get("expected_tools"),
    )
    assert result.success, f"Agent request failed: {result.error}"
    assert_not_graceful_degrade(result)

    score = score_completeness(result, golden["expected_elements"])
    score_collector.record(golden["query"], score)
    assert score.passed, (
        f"Completeness check failed: missing {score.details.get('missing')} "
        f"(found {score.details.get('found')}). "
        f"Response: {result.response[:300]}"
    )
