"""Regression tests for local example helpers."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from examples._interactive_chat import InteractiveChat
from examples.ai_service import ai_stream_service
from langchain_core.messages import AIMessage


class _FakeContext:
    def __init__(
        self, payload: dict | None = None, headers: dict | None = None
    ) -> None:
        self._payload = payload or {}
        self._headers = headers or {}

    def get_json(self) -> dict:
        return self._payload

    def get_headers(self) -> dict:
        return self._headers


class _FakeAgent:
    def __init__(self, message: AIMessage) -> None:
        self._message = message

    def invoke(self, *_args, **_kwargs):
        return {"messages": [self._message]}

    def stream(self, *_args, **_kwargs):
        yield ("updates", {"model": {"messages": [self._message]}})


@contextmanager
def _fake_saver_ctx(*_args, **_kwargs):
    saver = MagicMock()
    saver.setup.return_value = None
    yield saver


def test_interactive_chat_help_message_omits_dead_list_questions_command():
    chat = InteractiveChat(lambda _payload: {"body": {"choices": []}})

    assert "list_questions" not in chat._help_message


def test_interactive_chat_handles_terminal_empty_delta_chunk(capsys):
    chat = InteractiveChat(lambda _payload: {"body": {"choices": []}}, stream=True)

    chat._print_message({"delta": {}, "finish_reason": "stop"})

    assert capsys.readouterr().out == ""


def test_ai_stream_service_ignores_refusal_additional_kwargs_without_tool_calls():
    refusal_message = AIMessage(content="", additional_kwargs={"refusal": "declined"})
    context = _FakeContext({"messages": [{"role": "user", "content": "hi"}]})

    with (
        patch("examples.ai_service.get_database_uri", return_value="postgresql://test"),
        patch(
            "examples.ai_service.PostgresSaver.from_conn_string",
            side_effect=_fake_saver_ctx,
        ),
        patch(
            "examples.ai_service.get_graph_closure",
            return_value=lambda *_args, **_kwargs: _FakeAgent(refusal_message),
        ),
    ):
        generate, generate_stream = ai_stream_service(
            context,
            base_url="http://localhost:8000/v1",
            model_id="test-model",
        )

        response = generate(context)
        stream_chunks = list(generate_stream(context))

    assert response["body"]["choices"][0]["message"] is None
    assert stream_chunks == []
