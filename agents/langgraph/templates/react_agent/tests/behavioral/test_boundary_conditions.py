"""Boundary condition tests for the LangGraph React agent.

Tests edge-case inputs specific to the react agent's search tool
behavior — empty, long, special-character, and repeated queries.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.langgraph_react

BOUNDARY_TIMEOUT = 60.0


async def test_empty_query_no_crash(run_eval: Any) -> None:
    """Empty input should not crash the agent."""
    result = await run_eval("", timeout_seconds=BOUNDARY_TIMEOUT)
    assert result.success, f"Agent crashed on empty query: {result.error}"


async def test_very_long_query_no_crash(run_eval: Any) -> None:
    """Very long input (10k+ chars) should not crash or hang."""
    long_query = "What is OpenShift AI? " * 500  # ~10,500 chars
    result = await run_eval(long_query, timeout_seconds=BOUNDARY_TIMEOUT)
    assert result.success, (
        f"Agent crashed on long query ({len(long_query)} chars): {result.error}"
    )


async def test_special_characters_in_query(run_eval: Any) -> None:
    """Emoji, Unicode, and HTML-like chars should not crash the agent."""
    queries = [
        "What is OpenShift AI? \U0001f680\U0001f916",
        "Explain <b>OpenShift</b> & its 'features' in \"detail\"",
        "OpenShift AI —�什么？ ñ ü ö",
    ]
    for query in queries:
        result = await run_eval(query, timeout_seconds=BOUNDARY_TIMEOUT)
        assert result.success, (
            f"Agent crashed on special character query: {result.error}. "
            f"Query: {query[:100]}"
        )


async def test_repeated_queries_no_infinite_loop(run_eval: Any) -> None:
    """Repeated identical queries should all return within timeout."""
    query = "What is Red Hat OpenShift AI?"
    for i in range(5):
        result = await run_eval(query, timeout_seconds=BOUNDARY_TIMEOUT)
        assert result.success, (
            f"Agent failed on repeated query iteration {i + 1}: {result.error}"
        )


async def test_numeric_only_query(run_eval: Any) -> None:
    """Pure numeric input should be handled gracefully."""
    result = await run_eval("12345678", timeout_seconds=BOUNDARY_TIMEOUT)
    assert result.success, f"Agent crashed on numeric-only query: {result.error}"
