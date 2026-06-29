"""Unit tests for Langflow /api/v1/run protocol support in runner.py."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from harness.runner import (
    TaskConfig,
    _extract_langflow_response_text,
    _extract_langflow_tool_calls,
    run_task,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Extraction: response text
# ---------------------------------------------------------------------------


class TestExtractLangflowResponseText:
    """Tests for _extract_langflow_response_text()."""

    def test_primary_path(self, langflow_run_response):
        """Extracts text from results.message.text."""
        text = _extract_langflow_response_text(langflow_run_response)
        assert "Boston" in text
        assert "72°F" in text

    def test_fallback_to_artifacts(self):
        """Falls back to artifacts.message when results.message.text is missing."""
        data = {
            "outputs": [
                {
                    "outputs": [
                        {
                            "results": {"message": {}},
                            "artifacts": {"message": "Fallback text here"},
                        }
                    ]
                }
            ]
        }
        assert _extract_langflow_response_text(data) == "Fallback text here"

    def test_empty_response(self):
        """Returns empty string for empty/malformed data."""
        assert _extract_langflow_response_text({}) == ""
        assert _extract_langflow_response_text({"outputs": []}) == ""

    def test_none_text_uses_fallback(self):
        """When text is None, falls back to artifacts.message."""
        data = {
            "outputs": [
                {
                    "outputs": [
                        {
                            "results": {"message": {"text": None}},
                            "artifacts": {"message": "From artifacts"},
                        }
                    ]
                }
            ]
        }
        assert _extract_langflow_response_text(data) == "From artifacts"


# ---------------------------------------------------------------------------
# Extraction: tool calls
# ---------------------------------------------------------------------------


class TestExtractLangflowToolCalls:
    """Tests for _extract_langflow_tool_calls()."""

    def test_single_tool_call(self, langflow_run_response):
        """Extracts a single tool call with tool_input mapped to arguments."""
        calls = _extract_langflow_tool_calls(langflow_run_response)
        assert len(calls) == 1
        assert calls[0]["name"] == "get_forecast"
        assert calls[0]["arguments"] == {"city": "Boston", "days": 1}

    def test_multi_tool_calls(self):
        """Extracts multiple tool calls from multiple content blocks."""
        data = {
            "outputs": [
                {
                    "outputs": [
                        {
                            "results": {
                                "message": {
                                    "content_blocks": [
                                        {
                                            "title": "search",
                                            "contents": [
                                                {
                                                    "type": "tool_use",
                                                    "name": "web_search",
                                                    "tool_input": {"q": "test"},
                                                }
                                            ],
                                        },
                                        {
                                            "title": "calc",
                                            "contents": [
                                                {
                                                    "type": "tool_use",
                                                    "name": "calculator",
                                                    "tool_input": {"expr": "2+2"},
                                                }
                                            ],
                                        },
                                    ]
                                }
                            }
                        }
                    ]
                }
            ]
        }
        calls = _extract_langflow_tool_calls(data)
        assert len(calls) == 2
        assert calls[0]["name"] == "web_search"
        assert calls[1]["name"] == "calculator"
        assert calls[1]["arguments"] == {"expr": "2+2"}

    def test_no_tool_calls(self):
        """Returns empty list when no content_blocks or no tool_use entries."""
        data = {
            "outputs": [
                {
                    "outputs": [
                        {
                            "results": {
                                "message": {
                                    "text": "No tools used",
                                    "content_blocks": [],
                                }
                            }
                        }
                    ]
                }
            ]
        }
        assert _extract_langflow_tool_calls(data) == []

    def test_skips_non_tool_use_entries(self):
        """Entries with type != 'tool_use' are skipped."""
        data = {
            "outputs": [
                {
                    "outputs": [
                        {
                            "results": {
                                "message": {
                                    "content_blocks": [
                                        {
                                            "contents": [
                                                {"type": "text", "text": "hello"},
                                                {
                                                    "type": "tool_use",
                                                    "name": "search",
                                                    "tool_input": {},
                                                },
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            ]
        }
        calls = _extract_langflow_tool_calls(data)
        assert len(calls) == 1
        assert calls[0]["name"] == "search"

    def test_empty_response(self):
        """Returns empty list for empty/malformed data."""
        assert _extract_langflow_tool_calls({}) == []
        assert _extract_langflow_tool_calls({"outputs": []}) == []


# ---------------------------------------------------------------------------
# run_task() with langflow_run api_format
# ---------------------------------------------------------------------------


class TestRunTaskLangflow:
    """Tests for run_task() with api_format='langflow_run'."""

    def test_missing_flow_id_raises(self):
        """run_task raises ValueError when flow_id is not set."""
        config = TaskConfig(
            agent_url="http://agent:8080",
            query="hello",
            api_format="langflow_run",
            flow_id=None,
        )
        with pytest.raises(ValueError, match="flow_id is required"):
            asyncio.run(run_task(config))

    def test_url_construction(self, langflow_run_response):
        """URL is built as /api/v1/run/<flow_id>."""
        config = TaskConfig(
            agent_url="http://agent:8080",
            query="What is the weather?",
            api_format="langflow_run",
            flow_id="abc-123",
            extra_headers={"Authorization": "Bearer tok"},
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = langflow_run_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        result = asyncio.run(run_task(config, client=mock_client))

        call_args = mock_client.post.call_args
        assert call_args.args[0] == "http://agent:8080/api/v1/run/abc-123"

        payload = call_args.kwargs["json"]
        assert payload == {
            "input_value": "What is the weather?",
            "output_type": "chat",
            "input_type": "chat",
        }

        headers = call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"

        assert result.success is True
        assert "Boston" in result.response
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "get_forecast"
        assert result.tool_calls[0]["arguments"]["city"] == "Boston"

    def test_langflow_does_not_stream(self, langflow_run_response):
        """Langflow requests always use non-streaming POST, even if stream=True."""
        config = TaskConfig(
            agent_url="http://agent:8080",
            query="test",
            api_format="langflow_run",
            flow_id="f-1",
            stream=True,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = langflow_run_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        result = asyncio.run(run_task(config, client=mock_client))

        mock_client.post.assert_called_once()
        assert not hasattr(mock_client, "stream") or not mock_client.stream.called
        assert result.success is True

    def test_http_error_returns_failed_result(self):
        """HTTP errors return a failed TaskResult, not an exception."""
        config = TaskConfig(
            agent_url="http://agent:8080",
            query="test",
            api_format="langflow_run",
            flow_id="f-1",
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=httpx.Request("POST", "http://agent:8080/api/v1/run/f-1"),
                response=httpx.Response(500, text="Internal Server Error"),
            )
        )

        result = asyncio.run(run_task(config, client=mock_client))

        assert result.success is False
        assert result.error is not None and "500" in result.error


# ---------------------------------------------------------------------------
# Regression: chat_completions path unchanged
# ---------------------------------------------------------------------------


class TestRunTaskChatCompletionsUnchanged:
    """Verify the default chat_completions path still works."""

    def test_default_api_format(self):
        """TaskConfig defaults to chat_completions."""
        config = TaskConfig(agent_url="http://a:8080", query="hi")
        assert config.api_format == "chat_completions"
        assert config.flow_id is None
        assert config.extra_headers == {}

    def test_chat_completions_url(self):
        """chat_completions uses /chat/completions URL."""
        config = TaskConfig(agent_url="http://agent:8080", query="hi")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "hello"}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        result = asyncio.run(run_task(config, client=mock_client))

        call_args = mock_client.post.call_args
        assert call_args.args[0] == "http://agent:8080/chat/completions"
        assert result.success is True
        assert result.response == "hello"
