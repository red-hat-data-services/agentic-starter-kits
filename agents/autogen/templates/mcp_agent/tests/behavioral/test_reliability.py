"""Reliability (pass@k) evals for the AutoGen MCP agent.

Runs the same query multiple times to measure consistency. An agent
that passes once but fails intermittently is brittle and not
production-ready.

Queries run sequentially to avoid overwhelming the model endpoint.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from harness.scorers import Score
from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

pytestmark = [pytest.mark.autogen_mcp, pytest.mark.slow]

PASS_K_TIMEOUT = 60.0

_COMPUTATION_EVIDENCE = ["1141239"]


async def test_pass_at_k_single_tool(
    run_eval: Any, autogen_mcp_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Tool selection should succeed in >= threshold% of k runs.

    Runs the same add query k times sequentially. When tool_calls
    are exposed, checks via F1 scorer. Otherwise falls back to checking
    that the response contains the expected numeric result.
    """
    k = autogen_mcp_thresholds.get("pass_at_k", 8)
    query = "Use the add tool to compute 847392 + 293847"
    expected_tools = ["add"]
    threshold = autogen_mcp_thresholds.get("tool_selection_accuracy", 0.85)

    results = []
    for _ in range(k):
        result = await run_eval(
            query,
            expected_tools=expected_tools,
            timeout_seconds=PASS_K_TIMEOUT,
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
            text_normalized = re.sub(
                r"[\s,\u00a0\u2009\u202f]+", "", result.response.lower()
            )
            if any(term in text_normalized for term in _COMPUTATION_EVIDENCE):
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
    run_eval: Any, autogen_mcp_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response coherence should pass in >= threshold% of k runs.

    Ensures the agent produces structured, substantive responses
    consistently, not just occasionally.
    """
    k = autogen_mcp_thresholds.get("pass_at_k", 8)
    query = "Use the add tool to compute 847392 + 293847 and explain the result"
    threshold = autogen_mcp_thresholds.get("response_coherence_accuracy", 0.75)

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
