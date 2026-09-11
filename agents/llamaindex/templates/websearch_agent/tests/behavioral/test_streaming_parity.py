"""Streaming response test for the LlamaIndex Websearch agent."""

from __future__ import annotations

from typing import Any

import pytest
from harness.runner import TaskConfig, TaskResult, run_task

pytestmark = pytest.mark.llamaindex_websearch

PARITY_QUERY = "Search the web for the best AI platform"
PARITY_TIMEOUT = 45.0


async def _run_query(agent_url: str, client: Any, stream: bool) -> TaskResult:
    config = TaskConfig(
        agent_url=agent_url,
        query=PARITY_QUERY,
        timeout_seconds=PARITY_TIMEOUT,
        stream=stream,
    )
    return await run_task(config, client=client)


async def test_streaming_parity(agent_url: str, http_client: Any) -> None:
    """Both response modes should return usable responses."""
    result_sync = await _run_query(agent_url, http_client, stream=False)
    result_stream = await _run_query(agent_url, http_client, stream=True)

    assert result_sync.success, f"Non-streaming request failed: {result_sync.error}"
    assert result_stream.success, f"Streaming request failed: {result_stream.error}"

    assert result_sync.response.strip(), "Non-streaming response is empty"
    assert result_stream.response.strip(), "Streaming response is empty"
