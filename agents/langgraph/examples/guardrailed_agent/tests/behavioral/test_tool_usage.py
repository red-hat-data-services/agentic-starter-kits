"""Tool usage evals for the LangGraph Guardrailed agent.

The agent has a single tool: ``check_balance`` (dummy) that returns a canned
``$2,450.00`` checking balance. Most agents do not expose ``tool_calls`` in
the OpenAI-compatible response, so canned tool output is the primary proof
the tool ran (same approach as the react_agent evals).
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import assert_not_graceful_degrade, load_golden
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.langgraph_guardrailed

_CANNED_BALANCE = "2,450"


def _balance_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger check_balance."""
    return [
        q
        for q in load_golden()
        if q.get("expected_tools") == ["check_balance"]
        and _CANNED_BALANCE in q.get("expected_elements", [])
    ]


@pytest.mark.parametrize(
    "golden",
    _balance_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_check_balance_uses_canned_output(
    run_eval: Any, golden: dict[str, Any], score_collector: Any
) -> None:
    """Balance lookups must include canned check_balance output."""
    result = await run_eval(
        golden["query"],
        expected_tools=golden["expected_tools"],
    )
    assert result.success, f"Agent request failed: {result.error}"
    assert_not_graceful_degrade(result)

    text_lower = result.response.lower()
    found = [e for e in golden.get("expected_elements", []) if e.lower() in text_lower]
    assert len(found) > 0, (
        f"Response does not contain expected elements "
        f"{golden.get('expected_elements')}. check_balance may not have run. "
        f"Response: {result.response[:300]}"
    )
    assert _CANNED_BALANCE in text_lower, (
        f"Response missing canned $2,450 tool output. Response: {result.response[:300]}"
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
            "via canned check_balance output only.",
            stacklevel=1,
        )


async def test_no_hallucinated_tools(
    run_eval: Any, known_tools: list[str], score_collector: Any
) -> None:
    """Agent must only call tools that exist in its schema."""
    query = "What is the checking balance for account ACCT-12345?"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"
    assert_not_graceful_degrade(result)

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_hallucinated_tools(result, known_tools)
    score_collector.record(query, score)
    assert score.passed, (
        f"Hallucinated tools detected: {score.details.get('hallucinated')}"
    )


async def test_tool_call_has_valid_args(run_eval: Any, score_collector: Any) -> None:
    """All tool call arguments must be valid JSON with required fields."""
    query = "Please check the balance for account ACCT-12345"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"
    assert_not_graceful_degrade(result)

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_tool_call_validity(result)
    score_collector.record(query, score)
    assert score.passed, f"Invalid tool call arguments: {score.details.get('invalid')}"


async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls."""
    result = await run_eval("Hello")
    assert result.success, f"Agent request failed: {result.error}"
    assert_not_graceful_degrade(result)

    if result.tool_calls:
        assert len(result.tool_calls) == 0, (
            f"Greeting should not trigger tool calls, "
            f"but got: {[tc['name'] for tc in result.tool_calls]}"
        )

    text_lower = result.response.lower()
    assert not any(term in text_lower for term in ("2,450", "2450.00")), (
        "Greeting response appears to contain check_balance tool output — "
        "agent may have called the tool for a simple greeting"
    )
