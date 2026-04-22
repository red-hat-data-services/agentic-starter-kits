"""Reliability (pass@k) evals for the Vanilla Python OpenAI Responses agent.

Runs the same query multiple times to measure consistency. An agent
that passes once but fails intermittently is brittle and not
production-ready. We use k=8 as specified in the project thresholds.

NOTE: Queries run sequentially, not concurrently. Concurrent requests
to local Ollama overwhelm the model and cause timeouts, which measures
infrastructure limits rather than agent reliability.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from conftest import PRICE_EVIDENCE, REVIEW_EVIDENCE
from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

pytestmark = [pytest.mark.vanilla_python, pytest.mark.slow]

DEFAULT_K = 8
PASS_K_TIMEOUT = 60.0


@pytest.mark.asyncio
async def test_pass_at_k_single_tool(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Single-tool selection should succeed in >= threshold% of k runs.

    Runs the same price query k times sequentially. When tool_calls
    are exposed, checks via F1 scorer. Otherwise falls back to checking
    that the response contains evidence of price tool usage (weaker signal).
    """
    query = "What is the price of Nike shoes?"
    expected_tools = ["search_price"]
    threshold = vanilla_python_thresholds.get("tool_selection_accuracy", 0.85)
    k = vanilla_python_thresholds.get("pass_at_k", DEFAULT_K)

    passed_count = 0
    failures = 0
    used_fallback = 0
    for _ in range(k):
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
            used_fallback += 1
            text_lower = result.response.lower()
            if any(term in text_lower for term in PRICE_EVIDENCE):
                passed_count += 1

    if used_fallback == k - failures:
        warnings.warn(
            "tool_calls not exposed in any response — pass@k scored via "
            "content keywords only (weaker signal)",
            stacklevel=1,
        )

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} single-tool selection = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
        f"errors={failures})"
    )


@pytest.mark.asyncio
async def test_pass_at_k_multi_tool(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Multi-tool selection should succeed in >= threshold% of k runs.

    Runs a comparison query k times sequentially. Checks for evidence
    of both price and review tool usage in each response.
    """
    query = "Compare Nike and Adidas prices and reviews"
    expected_tools = ["search_price", "search_reviews"]
    threshold = vanilla_python_thresholds.get("multi_tool_accuracy", 0.75)
    k = vanilla_python_thresholds.get("pass_at_k", DEFAULT_K)

    passed_count = 0
    failures = 0
    used_fallback = 0
    for _ in range(k):
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
            used_fallback += 1
            text_lower = result.response.lower()
            has_price = any(term in text_lower for term in PRICE_EVIDENCE)
            has_review = any(term in text_lower for term in REVIEW_EVIDENCE)
            if has_price and has_review:
                passed_count += 1

    if used_fallback == k - failures:
        warnings.warn(
            "tool_calls not exposed in any response — pass@k scored via "
            "content keywords only (weaker signal)",
            stacklevel=1,
        )

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} multi-tool selection = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
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
    k = vanilla_python_thresholds.get("pass_at_k", DEFAULT_K)

    passed_count = 0
    failures = 0
    for _ in range(k):
        result = await run_eval(query, timeout_seconds=PASS_K_TIMEOUT)
        if not result.success:
            failures += 1
            continue
        score = score_plan_coherence(result)
        if score.passed:
            passed_count += 1

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} coherence = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
        f"errors={failures})"
    )
