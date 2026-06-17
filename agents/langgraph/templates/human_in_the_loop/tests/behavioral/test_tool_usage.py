"""Tool usage evals for the LangGraph Human-in-the-Loop agent.

Validates that the agent selects the create_file tool correctly for
file-creation requests and handles the HITL approval flow end-to-end.
Queries with approval="yes" complete the tool execution; queries with
approval="no" verify the agent handles rejection gracefully.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import load_golden
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.langgraph_hitl


def _approval_queries() -> list[dict[str, Any]]:
    """Return golden queries that trigger tool calls and get approved."""
    return [q for q in load_golden() if q.get("approval") == "yes"]


def _rejection_queries() -> list[dict[str, Any]]:
    """Return golden queries that trigger tool calls and get rejected."""
    return [q for q in load_golden() if q.get("approval") == "no"]


@pytest.mark.parametrize(
    "golden",
    _approval_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_tool_selection_accuracy(
    run_eval: Any, golden: dict[str, Any], score_collector: Any
) -> None:
    """Correct tool should be selected and approved for file-creation queries."""
    result = await run_eval(
        golden["query"],
        expected_tools=golden["expected_tools"],
        approval=golden.get("approval", "yes"),
    )
    assert result.success, f"Agent request failed: {result.error}"

    expected_elements = golden.get("expected_elements", [])
    if expected_elements:
        text_lower = result.response.lower()
        found = [e for e in expected_elements if e.lower() in text_lower]
        assert len(found) > 0, (
            f"Response does not contain expected elements {expected_elements}. "
            f"Response: {result.response[:300]}"
        )

    if result.tool_calls:
        score = score_tool_selection(result, golden["expected_tools"])
        score_collector.record(golden["query"], score)
        assert score.passed, (
            f"Tool selection failed: expected {golden['expected_tools']}, "
            f"got {score.details}"
        )
    else:
        warnings.warn(
            "tool_calls not exposed in response — tool selection scored "
            "via response content only. Enable MLflow tracing for full coverage.",
            stacklevel=1,
        )


@pytest.mark.parametrize(
    "golden",
    _rejection_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_tool_rejection(run_eval: Any, golden: dict[str, Any]) -> None:
    """Agent should handle tool rejection gracefully."""
    result = await run_eval(
        golden["query"],
        expected_tools=golden["expected_tools"],
        approval="no",
    )
    assert result.success, f"Agent request failed: {result.error}"
    assert len(result.response) > 0, "Response is empty after rejection"

    expected_elements = golden.get("expected_elements", [])
    if expected_elements:
        text_lower = result.response.lower()
        found = [e for e in expected_elements if e.lower() in text_lower]
        assert len(found) > 0, (
            f"Rejection response does not contain expected elements "
            f"{expected_elements}. Response: {result.response[:300]}"
        )


async def test_no_hallucinated_tools(
    run_eval: Any, known_tools: list[str], score_collector: Any
) -> None:
    """Agent must only call tools that exist in its schema."""
    result = await run_eval(
        "Create a file called example.txt with 'test content'",
        approval="yes",
    )
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_hallucinated_tools(result, known_tools)
    score_collector.record(
        "Create a file called example.txt with 'test content'", score
    )
    assert score.passed, (
        f"Hallucinated tools detected: {score.details.get('hallucinated')}"
    )


async def test_tool_call_has_valid_args(run_eval: Any, score_collector: Any) -> None:
    """All tool call arguments must be valid JSON with required fields."""
    result = await run_eval(
        "Create a file called readme.txt with the content 'Getting started'",
        approval="yes",
    )
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_tool_call_validity(result)
    score_collector.record(
        "Create a file called readme.txt with the content 'Getting started'", score
    )
    assert score.passed, f"Invalid tool call arguments: {score.details.get('invalid')}"


async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls."""
    result = await run_eval("Hello")
    assert result.success, f"Agent request failed: {result.error}"

    if result.tool_calls:
        assert len(result.tool_calls) == 0, (
            f"Greeting should not trigger tool calls, "
            f"but got: {[tc['name'] for tc in result.tool_calls]}"
        )

    text_lower = result.response.lower()
    assert "create_file" not in text_lower, (
        "Greeting response appears to contain create_file tool output — "
        "agent may have called create_file for a simple greeting"
    )
