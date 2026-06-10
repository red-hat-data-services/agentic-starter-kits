"""Latency evals for the Langflow Simple Tool Calling agent.

Validates that the agent stays within latency budgets defined in
configs/thresholds.yaml. Langflow has higher latency than standard
FastAPI agents due to flow execution overhead and external API calls
(Open-Meteo, NPS).
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers.latency import score_latency

pytestmark = pytest.mark.langflow_tool_calling


async def test_latency_under_threshold(
    run_eval: Any, langflow_tool_calling_thresholds: dict[str, Any]
) -> None:
    """Response latency must stay within the p95 threshold."""
    max_latency = langflow_tool_calling_thresholds["max_latency_p95"]
    result = await run_eval("What is the weather like in Boston today?")
    assert result.success, f"Agent request failed: {result.error}"

    score = score_latency(result, max_latency)
    assert score.passed, (
        f"Latency exceeded threshold: {result.latency_seconds:.2f}s > "
        f"{max_latency}s (details: {score.details})"
    )
