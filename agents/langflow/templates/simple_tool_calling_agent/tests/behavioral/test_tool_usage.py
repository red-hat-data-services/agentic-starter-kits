"""Tool usage evals for the Langflow Simple Tool Calling agent.

Validates that the agent selects, calls, and uses tools correctly
for various query types. The agent has three tools:
  get_forecast   — Open-Meteo weather API
  search_parks   — NPS park search API
  get_alerts     — NPS park alerts API

Tool calls are extracted from the Langflow /api/v1/run response
content_blocks by the harness runner — no MLflow enrichment needed.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import TOOL_OUTPUT_EVIDENCE, load_golden
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.langflow_tool_calling


def _factual_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger tool calls."""
    return [q for q in load_golden() if q.get("expected_tools")]


@pytest.mark.parametrize(
    "golden",
    _factual_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_tool_selection_accuracy(run_eval: Any, golden: dict[str, Any]) -> None:
    """Correct tool(s) should be selected for information-seeking queries.

    Primary check: tool_calls extracted from Langflow content_blocks.
    Secondary check: response contains evidence from the tool's output.
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
            "via response content only. Check that Langflow content_blocks "
            "are being parsed correctly by the harness runner.",
            stacklevel=1,
        )


async def test_no_hallucinated_tools(run_eval: Any, known_tools: list[str]) -> None:
    """Agent must only call tools that exist in its schema."""
    result = await run_eval("What is the weather in New York?")
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed — check Langflow content_blocks parsing")

    score = score_hallucinated_tools(result, known_tools)
    assert score.passed, (
        f"Hallucinated tools detected: {score.details.get('hallucinated')}"
    )


async def test_tool_call_has_valid_args(run_eval: Any) -> None:
    """All tool call arguments must be valid JSON with required fields."""
    result = await run_eval("What is the weather in Chicago?")
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed — check Langflow content_blocks parsing")

    score = score_tool_call_validity(result)
    assert score.passed, f"Invalid tool call arguments: {score.details.get('invalid')}"


async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls."""
    result = await run_eval("Hello!")
    assert result.success, f"Agent request failed: {result.error}"

    if result.tool_calls:
        assert len(result.tool_calls) == 0, (
            f"Greeting should not trigger tool calls, "
            f"but got: {[tc['name'] for tc in result.tool_calls]}"
        )

    text_lower = result.response.lower()
    tool_output_in_greeting = any(term in text_lower for term in TOOL_OUTPUT_EVIDENCE)
    assert not tool_output_in_greeting, (
        "Greeting response appears to contain tool output — "
        "agent may have called tools for a simple greeting"
    )
