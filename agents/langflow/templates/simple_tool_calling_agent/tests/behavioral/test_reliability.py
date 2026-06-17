"""Reliability (pass@k) evals for the Langflow Simple Tool Calling agent.

Runs the same query multiple times to measure consistency. An agent
that passes once but fails intermittently is brittle and not
production-ready. We use k=8 as specified in the project thresholds.

Tool calls are extracted from Langflow content_blocks by the harness
runner — no MLflow enrichment needed.

NOTE: Queries run sequentially, not concurrently. Concurrent requests
to Langflow can overwhelm the LLM backend and cause timeouts, which
measures infrastructure limits rather than agent reliability.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import TOOL_OUTPUT_EVIDENCE
from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

pytestmark = [pytest.mark.langflow_tool_calling, pytest.mark.slow]

PASS_K_TIMEOUT = 90.0


async def test_pass_at_k_tool_usage(
    run_eval: Any,
    langflow_tool_calling_thresholds: dict[str, Any],
    score_collector: Any,
) -> None:
    """Tool selection should succeed in >= threshold% of k runs.

    Runs the same weather query k times sequentially. When tool_calls
    are available (via content_blocks parsing), checks via F1 scorer.
    Otherwise falls back to checking that the response contains evidence
    of weather tool usage.
    """
    k = langflow_tool_calling_thresholds.get("pass_at_k", 8)
    query = "What is the weather like in Boston today?"
    expected_tools = ["get_forecast"]
    threshold = langflow_tool_calling_thresholds.get("tool_selection_accuracy", 0.75)

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
            score_collector.record(query, score)
            if score.passed:
                passed_count += 1
        else:
            used_fallback += 1
            text_lower = result.response.lower()
            if any(term in text_lower for term in TOOL_OUTPUT_EVIDENCE):
                passed_count += 1

    if used_fallback == k - failures:
        warnings.warn(
            "tool_calls not exposed in any response — pass@k scored via "
            "content keywords only (weaker signal)",
            stacklevel=1,
        )

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} tool selection = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
        f"errors={failures})"
    )


async def test_pass_at_k_response_quality(
    run_eval: Any,
    langflow_tool_calling_thresholds: dict[str, Any],
    score_collector: Any,
) -> None:
    """Response coherence should pass in >= threshold% of k runs.

    Ensures the agent produces structured, substantive responses
    consistently, not just occasionally.
    """
    k = langflow_tool_calling_thresholds.get("pass_at_k", 8)
    query = "What is the weather like in San Francisco today?"
    threshold = langflow_tool_calling_thresholds.get(
        "response_coherence_accuracy", 0.70
    )

    passed_count = 0
    failures = 0
    for _ in range(k):
        result = await run_eval(query, timeout_seconds=PASS_K_TIMEOUT)
        if not result.success:
            failures += 1
            continue
        score = score_plan_coherence(result)
        score_collector.record(query, score)
        if score.passed:
            passed_count += 1

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} coherence = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
        f"errors={failures})"
    )
