"""Tool usage evals for the LangGraph Guardrailed agent.

Validates that greetings do not trigger tools. Cases that require a real
``check_balance`` call are omitted: NeMo Guardrails 0.21 chat completions
drop ``tools``, so the agent never executes the tool.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
)

pytestmark = pytest.mark.langgraph_guardrailed


async def test_no_hallucinated_tools(
    run_eval: Any, known_tools: list[str], score_collector: Any
) -> None:
    """Agent must only call tools that exist in its schema."""
    query = "What is the checking balance for account ACCT-12345?"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

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

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_tool_call_validity(result)
    score_collector.record(query, score)
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
    assert not any(term in text_lower for term in ("2,450", "2450.00")), (
        "Greeting response appears to contain check_balance tool output — "
        "agent may have called the tool for a simple greeting"
    )
