"""Response quality evals for the LlamaIndex Websearch agent.

Validates that agent responses are coherent, structured, and substantive.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import load_golden
from harness.scorers.plan_coherence import score_completeness, score_plan_coherence

pytestmark = pytest.mark.llamaindex_websearch


def _queries_with_expected_elements() -> list[dict[str, Any]]:
    """Return golden queries that have non-empty expected_elements."""
    return [q for q in load_golden() if q.get("expected_elements")]


async def test_plan_coherence(run_eval: Any, score_collector: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    query = "Explain how to deploy a machine learning model on OpenShift"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"
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

    score = score_completeness(result, golden["expected_elements"])
    score_collector.record(golden["query"], score)
    assert score.passed, (
        f"Completeness check failed: missing {score.details.get('missing')} "
        f"(found {score.details.get('found')}). "
        f"Response: {result.response[:300]}"
    )
