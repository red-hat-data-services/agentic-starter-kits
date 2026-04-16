"""Reliability (pass@k) evals for the LangGraph React agent.

Runs the same query multiple times to measure consistency. An agent
that passes once but fails intermittently is brittle and not
production-ready. We use k=8 as specified in the project thresholds.

NOTE: Queries run sequentially, not concurrently. Concurrent requests
to local Ollama overwhelm the model and cause timeouts, which measures
infrastructure limits rather than agent reliability.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.langgraph_react, pytest.mark.slow]

from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

PASS_K_TIMEOUT = 60.0  # Per-request timeout for pass@k (longer than default)

_SEARCH_EVIDENCE = ["openshift ai", "openshift", "red hat"]


async def test_pass_at_k_tool_usage(
    run_eval: Any, react_thresholds: dict[str, Any]
) -> None:
    """Tool selection should succeed in >= threshold% of k runs.

    Runs the same factual query k times sequentially. When tool_calls
    are exposed, checks via F1 scorer. Otherwise falls back to checking
    that the response contains evidence of search tool usage.
    """
    k = react_thresholds.get("pass_at_k", 8)
    query = "What is Red Hat OpenShift AI?"
    expected_tools = ["search"]
    threshold = react_thresholds.get("tool_selection_accuracy", 0.85)

    passed_count = 0
    failures = 0
    for _ in range(k):
        result = await run_eval(
            query, expected_tools=expected_tools, timeout_seconds=PASS_K_TIMEOUT
        )
        if not result.success:
            failures += 1
            continue

        if result.tool_calls:
            score = score_tool_selection(result, expected_tools)
            if score.passed:
                passed_count += 1
        else:
            text_lower = result.response.lower()
            if any(term in text_lower for term in _SEARCH_EVIDENCE):
                passed_count += 1

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} tool selection = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
        f"errors={failures})"
    )


async def test_pass_at_k_response_quality(
    run_eval: Any, react_thresholds: dict[str, Any]
) -> None:
    """Response coherence should pass in >= threshold% of k runs.

    Ensures the agent produces structured, substantive responses
    consistently, not just occasionally.
    """
    k = react_thresholds.get("pass_at_k", 8)
    query = "Explain the benefits of using containers for ML workloads"
    threshold = react_thresholds.get("response_coherence_accuracy", 0.75)

    passed_count = 0
    failures = 0
    for _ in range(k):
        result = await run_eval(query, timeout_seconds=PASS_K_TIMEOUT)
        if not result.success:
            failures += 1
            continue
        score = score_plan_coherence(result)
        if score.passed:
            passed_count += 1

    pass_rate = passed_count / k
    assert pass_rate >= threshold, (
        f"pass@{k} coherence = {pass_rate:.2f} "
        f"(threshold={threshold:.2f}, passed={passed_count}/{k}, "
        f"errors={failures})"
    )
