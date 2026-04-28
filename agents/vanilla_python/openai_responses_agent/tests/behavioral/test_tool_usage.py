"""Tool usage evals for the Vanilla Python OpenAI Responses agent.

Validates that the agent selects, calls, and uses tools correctly
for various query types. The Vanilla Python agent has two tools:
``search_price(brand)`` and ``search_reviews(brand)`` that return
dummy product data.

NOTE: Most agents do not expose tool_calls in the OpenAI-compatible
response format -- the agent runs the full loop internally and
returns only the final message. When tool_calls are absent we verify
tool usage indirectly by checking that the response incorporates
content from the tool's expected output. When tool_calls ARE
present (e.g. after upstream adds them or MLflow tracing is enabled),
we also verify tool selection accuracy via scorers.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import PRICE_EVIDENCE, REVIEW_EVIDENCE, load_golden
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.vanilla_python


def _single_tool_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger exactly one tool call."""
    return [q for q in load_golden() if len(q.get("expected_tools", [])) == 1]


def _multi_tool_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger multiple tool calls."""
    return [q for q in load_golden() if len(q.get("expected_tools", [])) > 1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "golden",
    _single_tool_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_single_tool_selection(run_eval: Any, golden: dict[str, Any]) -> None:
    """Correct single tool should be selected for targeted queries.

    Primary check: response contains expected elements from the tool's output.
    Secondary check: if tool_calls are exposed, verify via F1 scorer.
    """
    result = await run_eval(
        golden["query"],
        expected_tools=golden["expected_tools"],
    )
    assert result.success, f"Agent request failed: {result.error}"

    expected_elements = golden.get("expected_elements", [])
    if expected_elements:
        text_lower = result.response.lower()
        found = [e for e in expected_elements if e.lower() in text_lower]
        assert len(found) > 0, (
            f"Response does not contain expected elements {expected_elements}. "
            f"The tool may not have been called. "
            f"Response: {result.response[:300]}"
        )

    if result.tool_calls:
        score = score_tool_selection(result, golden["expected_tools"])
        assert score.passed, (
            f"Tool selection failed: expected {golden['expected_tools']}, "
            f"got {score.details}"
        )
    else:
        warnings.warn(
            "tool_calls not exposed in response — tool selection scored "
            "via response content only. Enable MLflow tracing or upstream "
            "tool_calls in response format for full coverage.",
            stacklevel=1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "golden",
    _multi_tool_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_multi_tool_selection(run_eval: Any, golden: dict[str, Any]) -> None:
    """Multiple tools should be selected for queries needing both price and review data.

    Primary check: response contains evidence from both tools.
    Secondary check: if tool_calls are exposed, verify via F1 scorer.
    """
    result = await run_eval(
        golden["query"],
        expected_tools=golden["expected_tools"],
        timeout_seconds=60.0,
    )
    assert result.success, f"Agent request failed: {result.error}"

    text_lower = result.response.lower()
    has_price = any(term in text_lower for term in PRICE_EVIDENCE)
    has_review = any(term in text_lower for term in REVIEW_EVIDENCE)
    assert has_price and has_review, (
        f"Response lacks evidence of both tools. "
        f"has_price={has_price}, has_review={has_review}. "
        f"Response: {result.response[:300]}"
    )

    if result.tool_calls:
        score = score_tool_selection(result, golden["expected_tools"])
        assert score.passed, (
            f"Multi-tool selection failed: expected {golden['expected_tools']}, "
            f"got {score.details}"
        )
    else:
        warnings.warn(
            "tool_calls not exposed in response — multi-tool selection scored "
            "via response content only. Enable MLflow tracing or upstream "
            "tool_calls in response format for full coverage.",
            stacklevel=1,
        )


@pytest.mark.asyncio
async def test_no_hallucinated_tools(run_eval: Any, known_tools: list[str]) -> None:
    """Agent must only call tools that exist in its schema.

    When tool_calls are not exposed, this test passes trivially (no calls
    to check). It becomes meaningful once tool_calls are visible.
    """
    result = await run_eval("Tell me about Nike products")
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_hallucinated_tools(result, known_tools)
    assert score.passed, (
        f"Hallucinated tools detected: {score.details.get('hallucinated')}"
    )


@pytest.mark.asyncio
async def test_tool_call_has_valid_args(run_eval: Any) -> None:
    """All tool call arguments must be valid JSON with required fields.

    When tool_calls are not exposed, this test is skipped.
    """
    result = await run_eval("What is the price of Nike shoes?")
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_tool_call_validity(result)
    assert score.passed, f"Invalid tool call arguments: {score.details.get('invalid')}"


@pytest.mark.asyncio
async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls.

    Also checks that greeting responses are conversational, not product-data-based.
    The content heuristic is the primary signal — the tool_calls assertion
    is only meaningful when the agent exposes them.
    """
    result = await run_eval("Hello")
    assert result.success, f"Agent request failed: {result.error}"

    if result.tool_calls:
        assert len(result.tool_calls) == 0, (
            f"Greeting should not trigger tool calls, "
            f"but got: {[tc['name'] for tc in result.tool_calls]}"
        )

    text_lower = result.response.lower()
    has_price = any(term in text_lower for term in PRICE_EVIDENCE)
    has_review = any(term in text_lower for term in REVIEW_EVIDENCE)
    assert not has_price, (
        "Greeting response appears to contain price tool output — "
        "agent may have called search_price for a simple greeting"
    )
    assert not has_review, (
        "Greeting response appears to contain review tool output — "
        "agent may have called search_reviews for a simple greeting"
    )
