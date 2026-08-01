"""Offline unit tests for guardrails response classification helpers.

These run without a live NeMo Guardrails server so heuristic regressions
are caught in CI via ``make test``.
"""

from __future__ import annotations

import pytest
from guardrails_client import is_allowed_response, is_blocked_response


def _completion(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class TestIsBlockedResponse:
    @pytest.mark.parametrize(
        "payload",
        [
            {"error": {"message": "Blocked by content_safety_check_input rails."}},
            _completion(""),
            _completion("I'm sorry, I can't respond to that."),
            _completion("Blocked by topic_safety_check_input rails."),
        ],
    )
    def test_rail_block_signals(self, payload: dict) -> None:
        assert is_blocked_response(payload, http_status=200) is True

    @pytest.mark.parametrize(
        "content",
        [
            "Sorry for the wait! I'm here and ready to help you today.",
            "Your balance for ACCT-12345 is $1,234.56 as of today.",
            "Hello! Welcome to our banking service. How can I help you today?",
            "I'm sorry, I cannot access your bank account balance without "
            "additional identity verification. Please contact support.",
        ],
    )
    def test_substantive_responses_not_treated_as_rail_blocks(
        self, content: str
    ) -> None:
        assert is_blocked_response(_completion(content), http_status=200) is False

    def test_http_4xx_is_blocked(self) -> None:
        assert is_blocked_response({}, http_status=422) is True


class TestIsAllowedResponse:
    def test_banking_answer_allowed(self) -> None:
        payload = _completion("Your balance for ACCT-12345 is $1,234.56 as of today.")
        assert is_allowed_response(payload, http_status=200) is True

    def test_rail_refusal_not_allowed(self) -> None:
        payload = _completion("I'm sorry, I can't respond to that.")
        assert is_allowed_response(payload, http_status=200) is False

    def test_too_short_not_allowed(self) -> None:
        assert is_allowed_response(_completion("Yes."), http_status=200) is False
