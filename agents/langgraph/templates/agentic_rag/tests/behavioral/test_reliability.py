"""Reliability (pass@k) evals for the LangGraph Agentic RAG agent.

Runs the same query multiple times to measure consistency. An agent
that passes once but fails intermittently is brittle and not
production-ready. We use k=8 as specified in the project thresholds.

NOTE: Queries run sequentially, not concurrently. Concurrent requests
can overwhelm the model and cause timeouts, which measures
infrastructure limits rather than agent reliability.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from conftest import RETRIEVER_EVIDENCE
from harness.scorers import Score
from harness.scorers.plan_coherence import score_plan_coherence
from harness.scorers.tool_sequence import score_tool_selection

pytestmark = [pytest.mark.agentic_rag, pytest.mark.slow]

PASS_K_TIMEOUT = 60.0


async def test_pass_at_k_tool_usage(
    run_eval: Any, agentic_rag_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Tool selection should succeed in >= threshold% of k runs.

    Runs the same factual query k times sequentially. When tool_calls
    are exposed, checks via F1 scorer. Otherwise falls back to checking
    that the response contains evidence of retriever tool usage.
    """
    k = agentic_rag_thresholds.get("pass_at_k", 8)
    query = "What is RAG and how does it work?"
    expected_tools = ["retriever"]
    threshold = agentic_rag_thresholds.get("tool_selection_accuracy", 0.85)

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
    used_fallback = 0
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
            used_fallback += 1
            text_lower = result.response.lower()
            if any(term in text_lower for term in RETRIEVER_EVIDENCE):
                passed_count += 1
            else:
                inconclusive += 1

    if used_fallback == k - infra_failures:
        warnings.warn(
            "tool_calls not exposed in any response — pass@k scored via "
            "content keywords only (weaker signal)",
            stacklevel=1,
        )

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
    run_eval: Any, agentic_rag_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response coherence should pass in >= threshold% of k runs.

    Ensures the agent produces structured, substantive responses
    consistently, not just occasionally.
    """
    k = agentic_rag_thresholds.get("pass_at_k", 8)
    query = "Explain how vector databases work and why they are important for RAG"
    threshold = agentic_rag_thresholds.get("response_coherence_accuracy", 0.75)

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
