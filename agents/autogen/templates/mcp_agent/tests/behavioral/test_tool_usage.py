"""Tool usage evals for the AutoGen MCP agent.

Validates that the agent selects, calls, and uses tools correctly
for various query types. The MCP agent has two tested tools: ``add``
and ``sub`` (via an MCP server). ``invoke_churn`` exists but is not
tested because the backend deployment is not configured on this cluster.

The agent exposes tool_invocations[] in non-streaming JSON responses,
so tool_calls are available directly via the harness runner fallback.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

import pytest
from conftest import load_golden
from harness.assertions import assert_injection_resistance
from harness.scorers.safety import score_pii_leakage
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
)

pytestmark = pytest.mark.autogen_mcp


def _tool_queries() -> list[dict[str, Any]]:
    """Return golden queries that should trigger tool calls."""
    return [q for q in load_golden() if q.get("expected_tools")]


@pytest.mark.parametrize(
    "golden",
    _tool_queries(),
    ids=lambda q: q["query"][:60],
)
async def test_single_tool_selection(
    run_eval: Any, golden: dict[str, Any], score_collector: Any
) -> None:
    """Correct tool should be selected for computation queries.

    Primary check: response contains the expected numeric result.
    Secondary check: if tool_calls are exposed, verify via F1 scorer.
    """
    result = await run_eval(
        golden["query"],
        expected_tools=golden["expected_tools"],
    )
    assert result.success, f"Agent request failed: {result.error}"

    expected_elements = golden.get("expected_elements", [])
    if expected_elements:
        text_normalized = re.sub(
            r"[\s,\u00a0\u2009\u202f]+", "", result.response.lower()
        )
        found = [e for e in expected_elements if e.lower() in text_normalized]
        assert len(found) > 0, (
            f"Response does not contain expected elements {expected_elements}. "
            f"The tool may not have been called. "
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
            "via response content only.",
            stacklevel=1,
        )


async def test_adversarial_no_pii_leakage(run_eval: Any, score_collector: Any) -> None:
    """Adversarial prompt injection must not leak credentials or PII.

    Uses the harness score_pii_leakage scorer which checks 11 pattern
    types (API keys, bearer tokens, AWS keys, GitHub tokens, SSNs, etc.)
    and integrates with the scoring framework.
    """
    adversarial = [q for q in load_golden("adversarial") if q.get("rejected_elements")]
    assert adversarial, "No adversarial queries with rejected_elements found"
    query = adversarial[0]["query"]
    result = await run_eval(query)
    assert result.success, f"Agent request failed: {result.error}"

    score = score_pii_leakage(result)
    score_collector.record(query, score)
    assert score.passed, (
        f"PII/credential leakage detected: {score.details.get('pii_types_found')}. "
        f"Response: {result.response[:300]}"
    )


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


async def test_no_hallucinated_tools(
    run_eval: Any, known_tools: list[str], score_collector: Any
) -> None:
    """Agent must only call tools that exist in its schema.

    When tool_calls are not exposed, this test passes trivially.
    """
    query = "Use the add tool to compute 50 + 25"
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
    query = "Use the add tool to compute 123 + 456"
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

    assert not result.tool_calls, (
        f"Greeting should not trigger tool calls, "
        f"but got: {[tc['name'] for tc in result.tool_calls]}"
    )
