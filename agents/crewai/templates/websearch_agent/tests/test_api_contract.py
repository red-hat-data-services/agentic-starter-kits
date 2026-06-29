"""Regression tests for API-contract changes (RHAIENG-5747, RHAIENG-5748).

Covers:
- Empty messages validation returns 422 (not 500)
- Usage populated when CrewAI result.token_usage is present
- Usage stays None when token_usage is absent
"""

import os
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import ChatCompletionRequest


class TestEmptyMessagesValidation:
    def test_empty_messages_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatCompletionRequest(messages=[])
        assert "messages" in str(exc_info.value)

    def test_single_message_accepted(self):
        req = ChatCompletionRequest(messages=[{"role": "user", "content": "hello"}])
        assert len(req.messages) == 1


class TestCrewaiUsageExtraction:
    """Test the inline usage extraction logic from _handle_chat."""

    @staticmethod
    def _extract_usage_from_result(result):
        """Mirror the usage extraction logic from main._handle_chat."""
        usage = None
        token_usage = getattr(result, "token_usage", None)
        if token_usage:
            usage = {
                "prompt_tokens": getattr(token_usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(token_usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(token_usage, "total_tokens", 0) or 0,
            }
        return usage

    def test_returns_none_when_no_token_usage(self):
        result = SimpleNamespace()
        assert self._extract_usage_from_result(result) is None

    def test_returns_none_when_token_usage_is_none(self):
        result = SimpleNamespace(token_usage=None)
        assert self._extract_usage_from_result(result) is None

    def test_returns_usage_when_present(self):
        result = SimpleNamespace(
            token_usage=SimpleNamespace(
                prompt_tokens=15,
                completion_tokens=25,
                total_tokens=40,
            )
        )
        usage = self._extract_usage_from_result(result)
        assert usage == {
            "prompt_tokens": 15,
            "completion_tokens": 25,
            "total_tokens": 40,
        }

    def test_handles_zero_values(self):
        result = SimpleNamespace(
            token_usage=SimpleNamespace(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            )
        )
        usage = self._extract_usage_from_result(result)
        assert usage == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def test_handles_none_fields(self):
        result = SimpleNamespace(
            token_usage=SimpleNamespace(
                prompt_tokens=None,
                completion_tokens=10,
                total_tokens=10,
            )
        )
        usage = self._extract_usage_from_result(result)
        assert usage == {
            "prompt_tokens": 0,
            "completion_tokens": 10,
            "total_tokens": 10,
        }
