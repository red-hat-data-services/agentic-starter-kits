"""Reliability (pass@k) evals for the LangGraph Guardrailed agent."""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers import Score
from harness.scorers.plan_coherence import score_plan_coherence

pytestmark = [pytest.mark.langgraph_guardrailed, pytest.mark.slow]

PASS_K_TIMEOUT = 90.0


async def test_pass_at_k_tool_usage(
    run_eval: Any, guardrailed_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Tool selection should succeed in >= threshold% of k runs."""
    pytest.skip(
        "NeMo Guardrails 0.21 drops `tools` from chat completions, so "
        "check_balance never runs. Re-enable when the proxy forwards tools."
    )


async def test_pass_at_k_response_quality(
    run_eval: Any, guardrailed_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response coherence should pass in >= threshold% of k runs."""
    k = guardrailed_thresholds.get("pass_at_k", 8)
    query = "Explain the benefits of having both checking and savings accounts"
    threshold = guardrailed_thresholds.get("response_coherence_accuracy", 0.75)

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
