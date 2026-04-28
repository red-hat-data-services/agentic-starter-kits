"""Latency evals for the Vanilla Python OpenAI Responses agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml. Multi-tool queries are allowed a higher
threshold since they require multiple sequential tool calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from harness.scorers.latency import score_latency

pytestmark = pytest.mark.vanilla_python


@pytest.mark.asyncio
async def test_latency_single_tool(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Single-tool response latency must stay within the p95 threshold."""
    max_latency = vanilla_python_thresholds["max_latency_p95"]
    result = await run_eval("What is the price of Nike shoes?")
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )


@pytest.mark.asyncio
async def test_latency_multi_tool(
    run_eval: Any, vanilla_python_thresholds: dict[str, Any]
) -> None:
    """Multi-tool response latency must stay within 1.5x the p95 threshold."""
    max_latency = vanilla_python_thresholds["max_latency_p95"] * 1.5
    result = await run_eval("Compare Nike and Adidas prices and reviews")
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
