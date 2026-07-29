"""Unit tests for main.py helper functions."""

from unittest.mock import MagicMock

from openai import APIConnectionError as OpenAIConnectionError
from openai import APIError as OpenAIAPIError


def _make_openai_error(message: str) -> OpenAIAPIError:
    """Create a mock OpenAIAPIError with the given message."""
    req = MagicMock()
    return OpenAIAPIError(message=message, request=req, body=None)


class TestIsGuardrailsBlock:
    def _call(self, exc: Exception) -> bool:
        from main import _is_guardrails_block

        return _is_guardrails_block(exc)

    def test_content_safety_input_block(self):
        exc = _make_openai_error("Blocked by content_safety_check_input rails")
        assert self._call(exc) is True

    def test_content_safety_output_block(self):
        exc = _make_openai_error("Blocked by content_safety_check_output rails")
        assert self._call(exc) is True

    def test_topic_safety_block(self):
        exc = _make_openai_error("Blocked by topic_safety_check_input rails")
        assert self._call(exc) is True

    def test_generic_openai_error_not_matched(self):
        exc = _make_openai_error("Connection refused")
        assert self._call(exc) is False

    def test_non_openai_error_not_matched(self):
        exc = RuntimeError("Blocked by rails")
        assert self._call(exc) is False

    def test_partial_match_blocked_without_rails(self):
        exc = _make_openai_error("Blocked by firewall")
        assert self._call(exc) is False

    def test_partial_match_rails_without_blocked(self):
        exc = _make_openai_error("Error in rails processing")
        assert self._call(exc) is False

    def test_connection_error_not_matched(self):
        req = MagicMock()
        exc = OpenAIConnectionError(request=req)
        assert self._call(exc) is False
