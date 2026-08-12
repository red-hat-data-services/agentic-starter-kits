"""Regression tests for API-contract changes (RHAIENG-5747, RHAIENG-5748).

Covers:
- Empty messages validation returns 422 (not 500)
- _extract_usage populates usage when AIMessage.usage_metadata is present
- _extract_usage returns None when no metadata is available
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
from main import (
    _GRACEFUL_ERROR_MESSAGE,
    _MAX_INVOKE_ATTEMPTS,
    ChatCompletionRequest,
    _extract_usage,
    _invoke_with_retry,
)


class TestEmptyMessagesValidation:
    def test_empty_messages_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatCompletionRequest(messages=[])
        assert "messages" in str(exc_info.value)

    def test_single_message_accepted(self):
        req = ChatCompletionRequest(messages=[{"role": "user", "content": "hello"}])
        assert len(req.messages) == 1


class TestExtractUsage:
    def test_returns_none_when_no_ai_messages(self):
        messages = [HumanMessage(content="hi")]
        assert _extract_usage(messages) is None

    def test_returns_none_when_ai_has_no_metadata(self):
        messages = [AIMessage(content="response")]
        assert _extract_usage(messages) is None

    def test_returns_usage_when_metadata_present(self):
        msg = AIMessage(
            content="response",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
        )
        result = _extract_usage([msg])
        assert result == {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }

    def test_sums_across_multiple_ai_messages(self):
        messages = [
            AIMessage(
                content="thought",
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 10,
                    "total_tokens": 15,
                },
            ),
            ToolMessage(content="result", tool_call_id="tc1"),
            AIMessage(
                content="final",
                usage_metadata={
                    "input_tokens": 8,
                    "output_tokens": 12,
                    "total_tokens": 20,
                },
            ),
        ]
        result = _extract_usage(messages)
        assert result == {
            "prompt_tokens": 13,
            "completion_tokens": 22,
            "total_tokens": 35,
        }

    def test_skips_messages_without_metadata(self):
        messages = [
            AIMessage(content="no metadata"),
            AIMessage(
                content="has metadata",
                usage_metadata={
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                },
            ),
        ]
        result = _extract_usage(messages)
        assert result == {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "total_tokens": 10,
        }

    def test_returns_none_for_empty_list(self):
        assert _extract_usage([]) is None


class TestInvokeWithRetry:
    def test_succeeds_on_first_attempt(self):
        expected = {"messages": [AIMessage(content="hello")]}
        mock_agent = AsyncMock(ainvoke=AsyncMock(return_value=expected))
        result = asyncio.run(
            _invoke_with_retry(mock_agent, {"messages": []}, config={})
        )
        assert result == expected
        assert mock_agent.ainvoke.call_count == 1

    def test_succeeds_after_transient_failure(self):
        expected = {"messages": [AIMessage(content="recovered")]}
        exc = ValidationError.from_exception_data(
            title="test",
            line_errors=[
                {
                    "type": "dict_type",
                    "loc": ("x",),
                    "msg": "bad",
                    "input": "y",
                }
            ],
        )
        mock_agent = AsyncMock(ainvoke=AsyncMock(side_effect=[exc, expected]))
        with patch("main.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                _invoke_with_retry(mock_agent, {"messages": []}, config={})
            )
        assert result == expected
        assert mock_agent.ainvoke.call_count == 2

    def test_exhausts_retries_and_raises(self):
        exc = ValidationError.from_exception_data(
            title="test",
            line_errors=[
                {
                    "type": "dict_type",
                    "loc": ("x",),
                    "msg": "bad",
                    "input": "y",
                }
            ],
        )
        mock_agent = AsyncMock(ainvoke=AsyncMock(side_effect=exc))
        with patch("main.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValidationError):
                asyncio.run(_invoke_with_retry(mock_agent, {"messages": []}, config={}))
        assert mock_agent.ainvoke.call_count == _MAX_INVOKE_ATTEMPTS

    def test_non_retryable_error_propagates_immediately(self):
        mock_agent = AsyncMock(
            ainvoke=AsyncMock(side_effect=RuntimeError("unexpected"))
        )
        with pytest.raises(RuntimeError, match="unexpected"):
            asyncio.run(_invoke_with_retry(mock_agent, {"messages": []}, config={}))
        assert mock_agent.ainvoke.call_count == 1

    def test_malformed_tool_args_not_leaked_in_logs(self, caplog):
        malformed_args = "%4W!O;VL"
        exc = ValidationError.from_exception_data(
            title="AIMessage",
            line_errors=[
                {
                    "type": "dict_type",
                    "loc": ("tool_calls", 0, "args"),
                    "msg": "Input should be a valid dictionary",
                    "input": malformed_args,
                }
            ],
        )
        mock_agent = AsyncMock(ainvoke=AsyncMock(side_effect=exc))
        with (
            patch("main.asyncio.sleep", new_callable=AsyncMock),
            caplog.at_level(logging.WARNING, logger="main"),
        ):
            with pytest.raises(ValidationError):
                asyncio.run(_invoke_with_retry(mock_agent, {"messages": []}, config={}))
        assert caplog.records
        for record in caplog.records:
            assert malformed_args not in record.getMessage()


class TestHandleChatGracefulError:
    @pytest.mark.anyio
    async def test_returns_200_with_error_message_on_graceful_exception(self):
        class FakeAgent:
            async def ainvoke(self, *_args, **_kwargs):
                raise GraphRecursionError("recursion limit reached")

        class FakeSaver:
            async def setup(self):
                return None

            async def aget_tuple(self, _config):
                return None

        @asynccontextmanager
        async def fake_saver_ctx(*_args, **_kwargs):
            yield FakeSaver()

        with (
            patch.object(main, "DB_URI", "postgresql://test"),
            patch.object(
                main,
                "agent_graph_closure",
                lambda *_args, **_kwargs: FakeAgent(),
            ),
            patch(
                "main.AsyncPostgresSaver.from_conn_string",
                side_effect=fake_saver_ctx,
            ),
            patch("main.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await main._handle_chat(
                [HumanMessage(content="test")], "test-model", "test-thread", None
            )
        assert result["choices"][0]["message"]["content"] == _GRACEFUL_ERROR_MESSAGE
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["object"] == "chat.completion"
        assert result["context"] == []
        assert result["usage"] is None

    @pytest.mark.anyio
    async def test_still_returns_500_for_non_retryable_errors(self):
        class FakeAgent:
            async def ainvoke(self, *_args, **_kwargs):
                raise RuntimeError("server broke")

        class FakeSaver:
            async def setup(self):
                return None

            async def aget_tuple(self, _config):
                return None

        @asynccontextmanager
        async def fake_saver_ctx(*_args, **_kwargs):
            yield FakeSaver()

        with (
            patch.object(main, "DB_URI", "postgresql://test"),
            patch.object(
                main,
                "agent_graph_closure",
                lambda *_args, **_kwargs: FakeAgent(),
            ),
            patch(
                "main.AsyncPostgresSaver.from_conn_string",
                side_effect=fake_saver_ctx,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await main._handle_chat(
                    [HumanMessage(content="test")], "test-model", None, None
                )
        assert exc_info.value.status_code == 500
