"""Memory isolation evals for the LangGraph DB Memory agent.

Validates that conversation threads are isolated — messages sent on one
thread_id must not be visible to another thread_id.

Requires a running DB Memory agent with PostgreSQL configured.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.langgraph_db_memory


async def test_threads_do_not_leak(run_eval: Any) -> None:
    """Independent threads must not share conversation context."""
    thread_a = f"test-iso-a-{uuid.uuid4()}"
    thread_b = f"test-iso-b-{uuid.uuid4()}"

    nonce_a = f"xq{uuid.uuid4().hex[:6]}"
    nonce_b = f"zk{uuid.uuid4().hex[:6]}"

    r1 = await run_eval(
        f"My secret identifier is {nonce_a}. Remember it exactly.",
        thread_id=thread_a,
        timeout_seconds=30.0,
    )
    assert r1.success, f"Thread A setup failed: {r1.error}"

    r2 = await run_eval(
        f"My secret identifier is {nonce_b}. Remember it exactly.",
        thread_id=thread_b,
        timeout_seconds=30.0,
    )
    assert r2.success, f"Thread B setup failed: {r2.error}"

    r3 = await run_eval(
        "What is my secret identifier? Reply with only the identifier.",
        thread_id=thread_a,
        timeout_seconds=30.0,
    )
    assert r3.success, f"Thread A recall failed: {r3.error}"
    text_a = r3.response.lower()
    assert nonce_a in text_a, (
        f"Thread A should recall '{nonce_a}' but got: {r3.response[:300]}"
    )
    assert nonce_b not in text_a, (
        f"Thread A leaked context from thread B — '{nonce_b}' found in response. "
        f"Response: {r3.response[:300]}"
    )

    r4 = await run_eval(
        "What is my secret identifier? Reply with only the identifier.",
        thread_id=thread_b,
        timeout_seconds=30.0,
    )
    assert r4.success, f"Thread B recall failed: {r4.error}"
    text_b = r4.response.lower()
    assert nonce_b in text_b, (
        f"Thread B should recall '{nonce_b}' but got: {r4.response[:300]}"
    )
    assert nonce_a not in text_b, (
        f"Thread B leaked context from thread A — '{nonce_a}' found in response. "
        f"Response: {r4.response[:300]}"
    )
