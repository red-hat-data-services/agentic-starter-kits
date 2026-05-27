"""Memory persistence evals for the LangGraph DB Memory agent.

Validates that the agent retains conversation context across multiple
turns within the same thread_id, and that a new thread_id starts with
no prior context.

Requires a running DB Memory agent with PostgreSQL configured.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.langgraph_db_memory


async def test_memory_persists_across_turns(run_eval: Any) -> None:
    """Agent should recall context from a previous turn on the same thread."""
    thread = f"test-persist-{uuid.uuid4()}"

    result1 = await run_eval(
        "My favorite color is blue. Please remember that.",
        thread_id=thread,
        timeout_seconds=30.0,
    )
    assert result1.success, f"Turn 1 failed: {result1.error}"

    result2 = await run_eval(
        "What is my favorite color?",
        thread_id=thread,
        timeout_seconds=30.0,
    )
    assert result2.success, f"Turn 2 failed: {result2.error}"
    assert "blue" in result2.response.lower(), (
        f"Agent did not recall 'blue' from prior turn. "
        f"Response: {result2.response[:300]}"
    )


async def test_new_thread_has_no_prior_context(run_eval: Any) -> None:
    """A fresh thread_id should have no knowledge of other threads."""
    thread_a = f"test-ctx-a-{uuid.uuid4()}"
    thread_b = f"test-ctx-b-{uuid.uuid4()}"

    result1 = await run_eval(
        "My secret code word is 'pineapple'. Remember it.",
        thread_id=thread_a,
        timeout_seconds=30.0,
    )
    assert result1.success, f"Turn 1 (thread A) failed: {result1.error}"

    result2 = await run_eval(
        "What is my secret code word?",
        thread_id=thread_b,
        timeout_seconds=30.0,
    )
    assert result2.success, f"Turn 2 (thread B) failed: {result2.error}"
    assert "pineapple" not in result2.response.lower(), (
        f"New thread leaked context from thread A — 'pineapple' found in response. "
        f"Response: {result2.response[:300]}"
    )
