"""Regression tests for API-contract changes (RHAIENG-5747, RHAIENG-5748).

Covers:
- Empty messages validation returns 422 (not 500)
- _extract_usage populates usage when AIMessage.usage_metadata is present
- _extract_usage returns None when no metadata is available
"""

import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import ChatCompletionRequest, _extract_usage


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
