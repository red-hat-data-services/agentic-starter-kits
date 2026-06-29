"""Tool usage evals for the LangGraph Agentic RAG agent.

Validates that the agent selects, calls, and uses the retriever tool
correctly for various query types. The agent has a single tool:
``retriever`` tool backed by OGX vector search.

NOTE: The Agentic RAG agent does not expose tool_calls in the OpenAI-
compatible response context. When tool_calls are absent we verify tool
usage indirectly by checking that the response incorporates content
from the knowledge base. When tool_calls ARE present (via MLflow trace
enrichment), we also verify tool selection accuracy via scorers.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import RETRIEVER_EVIDENCE, load_golden
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.agentic_rag


def _factual_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger tool calls."""
    return [q for q in load_golden() if q.get("expected_tools")]


@pytest.mark.parametrize(
    "golden",
    _factual_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_tool_selection_accuracy(
    run_eval: Any, golden: dict[str, Any], score_collector: Any
) -> None:
    """Correct tool should be selected for information-seeking queries.

    Primary check: response contains content from the retriever output.
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
            f"The retriever tool may not have been called. "
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


async def test_no_hallucinated_tools(
    run_eval: Any, known_tools: list[str], score_collector: Any
) -> None:
    """Agent must only call tools that exist in its schema.

    When tool_calls are not exposed, this test passes trivially (no calls
    to check). It becomes meaningful once tool_calls are visible.
    """
    query = "What are vector databases?"
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
    """All tool call arguments must be valid JSON with required fields.

    When tool_calls are not exposed, this test is skipped.
    """
    query = "What is LangGraph?"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed in response — cannot verify")

    score = score_tool_call_validity(result)
    score_collector.record(query, score)
    assert score.passed, f"Invalid tool call arguments: {score.details.get('invalid')}"


async def test_adversarial_prompt_injection_resistance(run_eval: Any) -> None:
    """Adversarial queries should answer the legit part without leaking internals."""
    adversarial = [q for q in load_golden("adversarial") if q.get("rejected_elements")]
    assert adversarial, "No adversarial queries with rejected_elements found"

    for golden in adversarial:
        result = await run_eval(
            golden["query"],
            expected_tools=golden.get("expected_tools"),
        )
        assert result.success, f"Agent request failed: {result.error}"

        text_lower = result.response.lower()
        for elem in golden["expected_elements"]:
            assert elem.lower() in text_lower, (
                f"Response missing expected element '{elem}' — "
                f"agent may not have answered the legitimate question"
            )

        leaked = [e for e in golden["rejected_elements"] if e.lower() in text_lower]
        assert not leaked, (
            f"Prompt injection resistance failed — response contains "
            f"rejected elements {leaked}. Response: {result.response[:300]}"
        )


async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls.

    Also checks that greeting responses are conversational, not retrieval-based.
    """
    result = await run_eval("Hello")
    assert result.success, f"Agent request failed: {result.error}"

    if result.tool_calls:
        assert len(result.tool_calls) == 0, (
            f"Greeting should not trigger tool calls, "
            f"but got: {[tc['name'] for tc in result.tool_calls]}"
        )

    text_lower = result.response.lower()
    assert not any(term in text_lower for term in RETRIEVER_EVIDENCE), (
        "Greeting response appears to contain retriever output — "
        "agent may have called the retriever tool for a simple greeting"
    )
