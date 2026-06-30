"""Boundary condition tests for the LangGraph React agent.

Tests edge-case inputs specific to the react agent's search tool
behavior — numeric-only and mixed-script queries.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.scorers import Score

pytestmark = pytest.mark.langgraph_react


async def test_numeric_only_query(run_eval: Any, score_collector: Any) -> None:
    """Pure numeric input should be handled gracefully."""
    query = "12345678"
    result = await run_eval(query)
    assert result is not None, "Agent returned None for numeric-only query"

    if result.success:
        assert isinstance(result.response, str)

    score_collector.record(
        query,
        Score(
            name="boundary_robustness",
            value=1.0,
            passed=True,
            details={
                "latency_seconds": result.latency_seconds,
                "agent_success": result.success,
            },
        ),
    )


async def test_special_characters_mixed_scripts(
    run_eval: Any, score_collector: Any
) -> None:
    """Mixed-script Unicode characters should not crash the agent."""
    query = "OpenShift AI —什么？ ñ ü ö"
    result = await run_eval(query)
    assert result is not None, "Agent returned None for mixed-script query"

    if result.success:
        assert isinstance(result.response, str)

    score_collector.record(
        query,
        Score(
            name="boundary_robustness",
            value=1.0,
            passed=True,
            details={
                "latency_seconds": result.latency_seconds,
                "agent_success": result.success,
            },
        ),
    )
