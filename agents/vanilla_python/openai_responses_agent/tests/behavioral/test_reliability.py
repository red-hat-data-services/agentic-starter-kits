"""Reliability (pass@k) evals for the Vanilla Python OpenAI Responses agent.

Runs the same query multiple times to measure consistency. An agent
that passes once but fails intermittently is brittle and not
production-ready. We use k=8 as specified in the project thresholds.

NOTE: Queries run sequentially, not concurrently. Concurrent requests
to local Ollama overwhelm the model and cause timeouts, which measures
infrastructure limits rather than agent reliability.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.vanilla_python, pytest.mark.slow]

from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

K = 8  # Number of iterations for pass@k
PASS_K_TIMEOUT = 60.0  # Per-request timeout for pass@k (longer than default)

_PRICE_EVIDENCE = ["price", "cost", "$", "dollar"]
_REVIEW_EVIDENCE = ["review", "rating", "star", "recommend"]


@pytest.mark.asyncio
async def test_pass_at_k_single_tool(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Single-tool selection should succeed in >= threshold% of k runs.

    Runs the same price query k=8 times sequentially. When tool_calls
    are exposed, checks via F1 scorer. Otherwise falls back to checking
    that the response contains evidence of price tool usage.
    """
    query = "What is the price of Nike shoes?"
    expected_tools = ["search_price"]
    threshold = vanilla_python_thresholds.get("tool_selection_accuracy", 0.85)

    passed_count = 0
    failures = 0
    for _ in range(K):
        result = await run_eval(
            query, expected_tools=expected_tools, timeout_seconds=PASS_K_TIMEOUT
        )
        if not result.success:
            failures += 1
            continue

        if result.tool_calls:
            score = score_tool_selection(result, expected_tools)
            if score.passed:
                passed_count += 1
        else:
            text_lower = result.response.lower()
            if any(term in text_lower for term in _PRICE_EVIDENCE):
                passed_count += 1

    pass_rate = passed_count / K
    assert pass_rate >= threshold, (
        f"pass@{K} single-tool selection = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{K}, "
        f"errors={failures})"
    )


@pytest.mark.asyncio
async def test_pass_at_k_multi_tool(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Multi-tool selection should succeed in >= threshold% of k runs.

    Runs a comparison query k=8 times sequentially. Checks for evidence
    of both price and review tool usage in each response.
    """
    query = "Compare Nike and Adidas prices and reviews"
    expected_tools = ["search_price", "search_reviews"]
    threshold = vanilla_python_thresholds.get("multi_tool_accuracy", 0.75)

    passed_count = 0
    failures = 0
    for _ in range(K):
        result = await run_eval(
            query, expected_tools=expected_tools, timeout_seconds=PASS_K_TIMEOUT
        )
        if not result.success:
            failures += 1
            continue

        if result.tool_calls:
            score = score_tool_selection(result, expected_tools)
            if score.passed:
                passed_count += 1
        else:
            text_lower = result.response.lower()
            has_price = any(term in text_lower for term in _PRICE_EVIDENCE)
            has_review = any(term in text_lower for term in _REVIEW_EVIDENCE)
            if has_price and has_review:
                passed_count += 1

    pass_rate = passed_count / K
    assert pass_rate >= threshold, (
        f"pass@{K} multi-tool selection = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{K}, "
        f"errors={failures})"
    )


@pytest.mark.asyncio
async def test_pass_at_k_response_quality(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Response coherence should pass in >= threshold% of k runs.

    Ensures the agent produces structured, substantive responses
    consistently, not just occasionally.
    """
    query = "Which brand offers the best value - Nike or Adidas?"
    threshold = vanilla_python_thresholds.get("response_coherence_accuracy", 0.75)

    passed_count = 0
    failures = 0
    for _ in range(K):
        result = await run_eval(query, timeout_seconds=PASS_K_TIMEOUT)
        if not result.success:
            failures += 1
            continue
        score = score_plan_coherence(result)
        if score.passed:
            passed_count += 1

    pass_rate = passed_count / K
    assert pass_rate >= threshold, (
        f"pass@{K} coherence = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{K}, "
        f"errors={failures})"
    )
