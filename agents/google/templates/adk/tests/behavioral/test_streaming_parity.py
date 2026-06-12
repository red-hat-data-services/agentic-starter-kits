"""Streaming parity test for the Google ADK agent.

Verifies that streaming and non-streaming responses produce equivalent
results — same content substance and same tool calls. Only added for
agents classified as "Standard streaming" (emit delta.tool_calls in
standard OpenAI SSE chunks).
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.runner import TaskConfig, TaskResult, run_task

pytestmark = pytest.mark.google_adk

PARITY_QUERY = "Search the web for the best AI platform"
PARITY_TIMEOUT = 45.0


async def _run_query(agent_url: str, client: Any, stream: bool) -> TaskResult:
    config = TaskConfig(
        agent_url=agent_url,
        query=PARITY_QUERY,
        expected_tools=["dummy_web_search"],
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
    assert sync_tools or stream_tools, (
        "Expected tool calls for parity query, but neither mode exposed any"
    )
    assert sync_tools == stream_tools, (
        f"Tool calls differ: non-streaming={sync_tools}, streaming={stream_tools}"
    )
