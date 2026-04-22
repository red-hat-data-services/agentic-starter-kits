"""Response quality evals for the Vanilla Python OpenAI Responses agent.

Validates that agent responses are coherent, structured, and substantive.
Also checks that multi-tool responses synthesize data from both tools
and that responses contain all expected elements.
"""

from __future__ import annotations

from typing import Any

import pytest

from conftest import PRICE_EVIDENCE, REVIEW_EVIDENCE, load_golden
from harness.scorers.plan_coherence import score_completeness, score_plan_coherence

pytestmark = pytest.mark.vanilla_python


def _queries_with_expected_elements() -> list[dict[str, Any]]:
    """Return golden queries that have non-empty expected_elements."""
    return [q for q in load_golden() if q.get("expected_elements")]


@pytest.mark.asyncio
async def test_plan_coherence(run_eval: Any) -> None:
    """Response should have structure and substance (not a bare one-liner)."""
    result = await run_eval(
        "Compare Nike and Adidas prices and reviews",
        timeout_seconds=60.0,
    )
    assert result.success, f"Agent request failed: {result.error}"
    score = score_plan_coherence(result)
    assert score.passed, (
        f"Plan coherence check failed (score={score.value:.2f}): "
        f"{score.details}"
    )


@pytest.mark.asyncio
async def test_response_synthesizes_multi_tool_data(run_eval: Any) -> None:
    """Multi-tool query response should incorporate data from both tools.

    Checks that the response contains evidence of both price and review
    tool output, indicating the agent called both tools and synthesized
    the results.
    """
    result = await run_eval(
        "Compare Nike and Adidas prices and reviews",
        timeout_seconds=60.0,
    )
    assert result.success, f"Agent request failed: {result.error}"

    text_lower = result.response.lower()
    has_price = any(term in text_lower for term in PRICE_EVIDENCE)
    has_review = any(term in text_lower for term in REVIEW_EVIDENCE)
    assert has_price, (
        f"Response lacks price data — search_price may not have been called. "
        f"Response: {result.response[:300]}"
    )
    assert has_review, (
        f"Response lacks review data — search_reviews may not have been called. "
        f"Response: {result.response[:300]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "golden",
    _queries_with_expected_elements(),
    ids=lambda q: q["query"][:60],
)
async def test_response_completeness(
    run_eval: Any, golden: dict[str, Any]
) -> None:
    """Response should contain all expected elements from the golden dataset."""
    result = await run_eval(
        golden["query"],
        expected_tools=golden.get("expected_tools"),
    )
    assert result.success, f"Agent request failed: {result.error}"

    score = score_completeness(result, golden["expected_elements"])
    assert score.passed, (
        f"Completeness check failed: missing {score.details.get('missing')} "
        f"(found {score.details.get('found')}). "
        f"Response: {result.response[:300]}"
    )
