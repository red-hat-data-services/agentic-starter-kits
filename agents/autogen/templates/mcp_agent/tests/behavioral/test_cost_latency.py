"""Latency evals for the AutoGen MCP agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.latency import score_latency

pytestmark = pytest.mark.autogen_mcp


async def test_latency_single_tool(
    run_eval: Any, autogen_mcp_thresholds: dict[str, Any], score_collector: Any
) -> None:
    """Response latency for a single-tool call must stay within the p95 threshold."""
    max_latency = autogen_mcp_thresholds["max_latency_p95"]
    result = await run_eval("Use the add tool to compute 55555 + 44444")
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    score_collector.record("Use the add tool to compute 55555 + 44444", score)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
