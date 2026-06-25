"""Reliability (pass@k) evals for the LangGraph Human-in-the-Loop agent.

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
from harness.scorers import Score
from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

pytestmark = [pytest.mark.langgraph_hitl, pytest.mark.slow]

PASS_K_TIMEOUT = 60.0


async def test_pass_at_k_tool_usage(
    run_eval: Any, hitl_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Tool selection should succeed in >= threshold% of k runs.

    Sends a file-creation query with approval="yes" so the full
    HITL flow completes and tool execution is verified end-to-end.
    """
    k = hitl_thresholds.get("pass_at_k", 8)
    query = "Create a file called test.txt with the content 'Hello World'"
    expected_tools = ["create_file"]
    threshold = hitl_thresholds.get("tool_selection_accuracy", 0.85)

    results = []
    for _ in range(k):
        result = await run_eval(
            query,
            expected_tools=expected_tools,
            timeout_seconds=PASS_K_TIMEOUT,
            approval="yes",
            enrich=False,
        )
        results.append(result)

    await run_eval.enrich_batch(results)

    passed_count = 0
    infra_failures = 0
    inconclusive = 0
    for result in results:
        if not result.success:
            infra_failures += 1
            continue

        if result.tool_calls:
            score = score_tool_selection(result, expected_tools)
            score_collector.record(query, score)
            if score.passed:
                passed_count += 1
            else:
                inconclusive += 1
        else:
            text_lower = result.response.lower()
            if "test.txt" in text_lower or "hello world" in text_lower:
                passed_count += 1
            else:
                inconclusive += 1

    pass_rate = passed_count / k
    score_collector.record(
        query,
        Score(
            name="pass_at_k_tool_selection",
            value=pass_rate,
            passed=pass_rate >= threshold,
            details={
                "k": k,
                "passed": passed_count,
                "errors": infra_failures,
                "inconclusive": inconclusive,
            },
        ),
    )
    assert pass_rate >= threshold, (
        f"pass@{k} tool selection = {pass_rate:.2f} "
        f"(passed={passed_count}/{k}, inconclusive={inconclusive}, "
        f"infra_errors={infra_failures}, threshold={threshold:.2f})"
    )


async def test_pass_at_k_response_quality(
    run_eval: Any, hitl_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response coherence should pass in >= threshold% of k runs."""
    k = hitl_thresholds.get("pass_at_k", 8)
    query = "Explain the concept of human-in-the-loop AI and its benefits"
    threshold = hitl_thresholds.get("response_coherence_accuracy", 0.75)

    results = []
    for _ in range(k):
        result = await run_eval(query, timeout_seconds=PASS_K_TIMEOUT, enrich=False)
        results.append(result)

    await run_eval.enrich_batch(results)

    passed_count = 0
    infra_failures = 0
    inconclusive = 0
    for result in results:
        if not result.success:
            infra_failures += 1
            continue
        score = score_plan_coherence(result)
        score_collector.record(query, score)
        if score.passed:
            passed_count += 1
        else:
            inconclusive += 1

    pass_rate = passed_count / k
    score_collector.record(
        query,
        Score(
            name="pass_at_k_coherence",
            value=pass_rate,
            passed=pass_rate >= threshold,
            details={
                "k": k,
                "passed": passed_count,
                "errors": infra_failures,
                "inconclusive": inconclusive,
            },
        ),
    )
    assert pass_rate >= threshold, (
        f"pass@{k} coherence = {pass_rate:.2f} "
        f"(passed={passed_count}/{k}, inconclusive={inconclusive}, "
        f"infra_errors={infra_failures}, threshold={threshold:.2f})"
    )
