"""Tool usage evals for the LangGraph React agent.

Validates that the agent selects, calls, and uses tools correctly
for various query types. The React agent has a single tool: ``search``
(dummy_web_search) that returns a canned answer about Red Hat OpenShift AI.

NOTE: Most agents do not expose tool_calls in the OpenAI-compatible
response format -- the agent runs the full ReAct loop internally and
returns only the final message. When tool_calls are absent we verify
tool usage indirectly by checking that the response incorporates
content from the search tool's canned output. When tool_calls ARE
present (e.g. after upstream adds them or MLflow tracing is enabled),
we also verify tool selection accuracy via scorers.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.langgraph_react


def _load_golden(category: str | None = None) -> list[dict[str, Any]]:
    """Load golden queries, optionally filtering by category."""
    path = Path(__file__).parent / "fixtures" / "golden_queries.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    queries = data.get("queries", [])
    if category:
        queries = [q for q in queries if q.get("category") == category]
    return queries


def _factual_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger tool calls."""
    return [q for q in _load_golden() if q.get("expected_tools")]


@pytest.mark.parametrize(
    "golden",
    _factual_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_tool_selection_accuracy(run_eval: Any, golden: dict[str, Any]) -> None:
    """Correct tool should be selected for information-seeking queries.

    Primary check: response contains content from the search tool's output.
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
            f"The search tool may not have been called. "
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


async def test_no_hallucinated_tools(run_eval: Any, known_tools: list[str]) -> None:
    """Agent must only call tools that exist in its schema.

    When tool_calls are not exposed, this test passes trivially (no calls
    to check). It becomes meaningful once tool_calls are visible.
    """
    result = await run_eval("Tell me about Kubernetes operators")
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_hallucinated_tools(result, known_tools)
    assert score.passed, (
        f"Hallucinated tools detected: {score.details.get('hallucinated')}"
    )


async def test_tool_call_has_valid_args(run_eval: Any) -> None:
    """All tool call arguments must be valid JSON with required fields.

    When tool_calls are not exposed, this test is skipped.
    """
    result = await run_eval("What is OpenShift AI?")
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_tool_call_validity(result)
    assert score.passed, f"Invalid tool call arguments: {score.details.get('invalid')}"


async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls.

    Also checks that greeting responses are conversational, not search-based.
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
    assert "openshift ai" not in text_lower, (
        "Greeting response appears to contain search tool output — "
        "agent may have called search tool for a simple greeting"
    )
