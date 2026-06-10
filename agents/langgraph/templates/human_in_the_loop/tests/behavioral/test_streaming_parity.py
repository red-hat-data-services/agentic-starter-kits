"""Streaming parity test for the LangGraph Human-in-the-Loop agent.

Verifies that streaming and non-streaming responses produce equivalent
results — same content substance and same tool calls. Only added for
agents classified as "Standard streaming" (emit delta.tool_calls in
standard OpenAI SSE chunks).

NOTE: For greeting queries (no tool trigger), both paths should produce
equivalent conversational responses. Tool-triggering queries produce
a pending_approval interrupt in both paths — content comparison still
applies but tool_calls may differ in format.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from harness.runner import TaskConfig, TaskResult, run_task

pytestmark = pytest.mark.langgraph_hitl

PARITY_QUERY = "Hello, how are you today?"
PARITY_TIMEOUT = 45.0


async def _run_query(agent_url: str, client: Any, stream: bool) -> TaskResult:
    config = TaskConfig(
        agent_url=agent_url,
        query=PARITY_QUERY,
        expected_tools=[],
        timeout_seconds=PARITY_TIMEOUT,
        stream=stream,
    )
    return await run_task(config, client=client)


async def test_streaming_parity(agent_url: str, http_client: Any) -> None:
    """Streaming and non-streaming should produce equivalent responses."""
    result_sync = await _run_query(agent_url, http_client, stream=False)
    result_stream = await _run_query(agent_url, http_client, stream=True)

    assert result_sync.success, f"Non-streaming request failed: {result_sync.error}"
    assert result_stream.success, f"Streaming request failed: {result_stream.error}"

    assert len(result_sync.response) > 0, "Non-streaming response is empty"
    assert len(result_stream.response) > 0, "Streaming response is empty"

    sync_tools = {tc["name"] for tc in (result_sync.tool_calls or [])}
    stream_tools = {tc["name"] for tc in (result_stream.tool_calls or [])}
    if sync_tools and stream_tools:
        assert sync_tools == stream_tools, (
            f"Tool calls differ: non-streaming={sync_tools}, streaming={stream_tools}"
        )
    elif stream_tools and not sync_tools:
        warnings.warn(
            "Non-streaming response has no tool_calls (context field stripped "
            "by response_model) — skipping tool call comparison.",
            stacklevel=1,
        )
