"""Tool usage evals for the A2A LangGraph-CrewAI agent.

Validates that the LangGraph orchestrator delegates to the CrewAI
specialist via ask_crew_specialist for specialized queries.

Tool calls are extracted from MLflow traces via MLflowTraceClient --
the /chat/completions shim does not expose tool_calls in the response
body. When MLflow is configured, enrich_eval_result() pulls
SpanType.TOOL spans into TaskResult.tool_calls.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import SPECIALIST_EVIDENCE, load_golden
from harness.assertions import assert_injection_resistance
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.a2a_langgraph_crewai


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
    """Correct tool should be selected for specialist-worthy queries.

    Primary check: tool_calls extracted from MLflow traces via enrichment.
    Secondary check: response contains evidence from the specialist's output.
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
            f"The specialist tool may not have been called. "
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
            "via response content only. Set MLFLOW_TRACKING_URI and "
            "MLFLOW_EXPERIMENT_NAME to enable MLflow trace enrichment "
            "for full tool_calls extraction.",
            stacklevel=1,
        )


async def test_no_hallucinated_tools(
    run_eval: Any, known_tools: list[str], score_collector: Any
) -> None:
    """Agent must only call tools that exist in its schema.

    Requires MLflow trace enrichment to populate tool_calls.
    """
    query = "Tell me about Kubernetes operators"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed — enable MLflow trace enrichment")

    score = score_hallucinated_tools(result, known_tools)
    score_collector.record(query, score)
    assert score.passed, (
        f"Hallucinated tools detected: {score.details.get('hallucinated')}"
    )


async def test_tool_call_has_valid_args(run_eval: Any, score_collector: Any) -> None:
    """All tool call arguments must be valid JSON with required fields.

    Requires MLflow trace enrichment to populate tool_calls.
    """
    query = "Ask the specialist about OpenShift AI"
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

    if not result.tool_calls:
        pytest.skip("tool_calls not exposed — enable MLflow trace enrichment")

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
        assert_injection_resistance(result, golden)


async def test_tool_not_called_for_greeting(run_eval: Any) -> None:
    """Simple greetings should not trigger any tool calls.

    Also checks that greeting responses are conversational, not specialist-based.
    """
    result = await run_eval("Hello")
    assert result.success, f"Agent request failed: {result.error}"

    if result.tool_calls:
        assert len(result.tool_calls) == 0, (
            f"Greeting should not trigger tool calls, "
            f"but got: {[tc['name'] for tc in result.tool_calls]}"
        )

    text_lower = result.response.lower()
    specialist_in_greeting = any(term in text_lower for term in SPECIALIST_EVIDENCE)
    assert not specialist_in_greeting, (
        "Greeting response appears to contain specialist tool output — "
        "agent may have called ask_crew_specialist for a simple greeting"
    )
