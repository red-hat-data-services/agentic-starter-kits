"""Streaming parity evals for the LangGraph DB Memory agent.

Verifies that the agent produces equivalent results in streaming and
non-streaming modes. Sends the same query with stream=false and
stream=true, then asserts both produce non-empty content with shared
key terms, and (when tool_calls are available) the same set of tool names.

Uses run_task directly with explicit stream= in TaskConfig — does NOT
use the run_eval fixture since it hardcodes STREAM.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.runner import TaskConfig, run_task

pytestmark = pytest.mark.langgraph_db_memory

_PARITY_QUERY = "What is Red Hat OpenShift AI?"
_EXPECTED_TERMS = ["openshift", "red hat"]


async def test_streaming_parity_content(agent_url: str, http_client: Any) -> None:
    """Both streaming and non-streaming should produce non-empty, overlapping content."""
    config_sync = TaskConfig(
        agent_url=agent_url,
        query=_PARITY_QUERY,
        expected_tools=["search"],
        timeout_seconds=30.0,
        stream=False,
    )
    config_stream = TaskConfig(
        agent_url=agent_url,
        query=_PARITY_QUERY,
        expected_tools=["search"],
        timeout_seconds=30.0,
        stream=True,
    )

    result_sync = await run_task(config_sync, client=http_client)
    result_stream = await run_task(config_stream, client=http_client)

    assert result_sync.success, f"Non-streaming request failed: {result_sync.error}"
    assert result_stream.success, f"Streaming request failed: {result_stream.error}"

    assert result_sync.response.strip(), "Non-streaming response is empty"
    assert result_stream.response.strip(), "Streaming response is empty"

    sync_lower = result_sync.response.lower()
    stream_lower = result_stream.response.lower()
    for term in _EXPECTED_TERMS:
        assert term in sync_lower, (
            f"Non-streaming response missing expected term '{term}'"
        )
        assert term in stream_lower, (
            f"Streaming response missing expected term '{term}'"
        )


async def test_streaming_parity_tool_calls(agent_url: str, http_client: Any) -> None:
    """When tool_calls are available, both modes should report the same tool set."""
    config_sync = TaskConfig(
        agent_url=agent_url,
        query=_PARITY_QUERY,
        expected_tools=["search"],
        timeout_seconds=30.0,
        stream=False,
    )
    config_stream = TaskConfig(
        agent_url=agent_url,
        query=_PARITY_QUERY,
        expected_tools=["search"],
        timeout_seconds=30.0,
        stream=True,
    )

    result_sync = await run_task(config_sync, client=http_client)
    result_stream = await run_task(config_stream, client=http_client)

    assert result_sync.success, f"Non-streaming request failed: {result_sync.error}"
    assert result_stream.success, f"Streaming request failed: {result_stream.error}"

    if not result_sync.tool_calls and not result_stream.tool_calls:
        pytest.skip("tool_calls not exposed in either mode — cannot compare")

    sync_tools = {tc["name"] for tc in (result_sync.tool_calls or [])}
    stream_tools = {tc["name"] for tc in (result_stream.tool_calls or [])}

    if sync_tools or stream_tools:
        assert sync_tools == stream_tools, (
            f"Tool sets differ: sync={sync_tools}, stream={stream_tools}"
        )
