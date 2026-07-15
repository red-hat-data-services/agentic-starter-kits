"""Boundary condition tests for agent robustness.

Verifies that the agent handles edge-case inputs gracefully:
empty queries, very long queries, special characters, and
repeated identical queries.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.adversarial


class TestEmptyInput:
    """Tests for empty or whitespace-only queries."""

    async def test_empty_query(self, run_eval):
        """Empty string query should be handled gracefully without crashing."""
        result = await run_eval("")

        # Agent may return an error or a polite refusal -- either is acceptable.
        # The key assertion is that it does not crash (result object exists).
        assert result is not None, "Agent returned None for empty query"
        if result.success:
            assert isinstance(result.response, str)


class TestLongInput:
    """Tests for very long queries."""

    async def test_very_long_query(self, run_eval):
        """10,000 character query should not crash the agent."""
        long_query = "What is the weather? " * 500  # ~10,500 chars
        result = await run_eval(long_query, timeout_seconds=60.0)

        # Agent may truncate, refuse, or answer -- all acceptable.
        # Must not crash.
        assert result is not None, "Agent returned None for very long query"


class TestSpecialCharacters:
    """Tests for special characters in queries."""

    @pytest.mark.parametrize(
        "query,description",
        [
            (
                "\u2603 What is the weather? \U0001f600\U0001f30d",
                "emoji and unicode symbols",
            ),
            (
                "query with \"quotes\" and 'apostrophes' and <html>&tags</html>",
                "HTML-like and quote characters",
            ),
        ],
        ids=["emoji_unicode", "html_quotes"],
    )
    async def test_special_characters(self, run_eval, query, description):
        """Special characters should not crash the agent."""
        result = await run_eval(query)

        assert result is not None, f"Agent returned None for {description}"


@pytest.mark.slow
class TestRepeatedQueries:
    """Tests for repeated identical queries."""

    async def test_repeated_queries(self, run_eval):
        """Same query sent 5 times should not cause infinite loops or crashes."""
        query = "What is the weather in Denver?"
        results = []

        for i in range(5):
            result = await run_eval(query)
            assert result is not None, f"Agent returned None on iteration {i + 1}"
            results.append(result)

        for i, result in enumerate(results):
            assert result.latency_seconds < 60.0, (
                f"Iteration {i + 1} took {result.latency_seconds:.1f}s, "
                "possible infinite loop"
            )
