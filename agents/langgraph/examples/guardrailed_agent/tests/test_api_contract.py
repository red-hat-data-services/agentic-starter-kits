"""API-contract unit tests for the guardrailed agent (RHAIENG-6912).

Covers:
- Empty messages validation returns ValidationError / 422 (not 500)
- _extract_usage populates usage when AIMessage.usage_metadata is present
- Local TestClient smoke of GET /health and POST /chat/completions
  (JSON + SSE) with the guardrails proxy mocked
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai import APIError as OpenAIAPIError
from pydantic import ValidationError
from starlette.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
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


def _fake_graph(*, content: str = "Your checking balance is $2,450.00.") -> AsyncMock:
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "messages": [
                HumanMessage(content="What is my balance?"),
                AIMessage(content=content),
            ]
        }
    )

    async def _astream_events(*_args, **_kwargs):
        chunk = MagicMock()
        chunk.content = content
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": chunk},
        }

    graph.astream_events = _astream_events
    return graph


@pytest.fixture
def api_client():
    """TestClient with guardrails proxy and graph mocked (no live proxy/LLM)."""
    fake_graph = _fake_graph()
    mock_health = MagicMock(status_code=200)
    env = {
        "BASE_URL": "http://localhost:8090/v1",
        "MODEL_ID": "test-model",
        "API_KEY": "test-key",
        "AUTH_ENABLED": "false",
    }
    with (
        patch.dict(os.environ, env, clear=False),
        patch("main.enable_tracing"),
        patch("main.get_graph_closure", return_value=fake_graph),
        patch.object(
            main._health_client, "get", new=AsyncMock(return_value=mock_health)
        ),
    ):
        with TestClient(main.app) as client:
            yield client, fake_graph


class TestHealthEndpoint:
    def test_health_ok_when_guardrails_mocked(self, api_client):
        client, _ = api_client
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["agent_initialized"] is True
        assert body["guardrails_reachable"] is True


class TestChatCompletionsEndpoint:
    def test_empty_messages_returns_422(self, api_client):
        client, _ = api_client
        response = client.post(
            "/chat/completions",
            json={"messages": [], "stream": False},
        )
        assert response.status_code == 422

    def test_json_completion_success(self, api_client):
        client, _ = api_client
        response = client.post(
            "/chat/completions",
            json={
                "messages": [{"role": "user", "content": "What is my balance?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert "2,450" in body["choices"][0]["message"]["content"]

    def test_sse_completion_success(self, api_client):
        client, _ = api_client
        with client.stream(
            "POST",
            "/chat/completions",
            json={
                "messages": [{"role": "user", "content": "What is my balance?"}],
                "stream": True,
            },
        ) as response:
            assert response.status_code == 200
            chunks = list(response.iter_lines())
        assert any(line.startswith("data: ") for line in chunks)
        assert any(line.strip() == "data: [DONE]" for line in chunks)
        content_parts = []
        for line in chunks:
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            payload = json.loads(line[len("data: ") :])
            delta = payload.get("choices", [{}])[0].get("delta", {})
            if delta.get("content"):
                content_parts.append(delta["content"])
        assert "".join(content_parts)

    def test_guardrails_block_returns_refusal(self, api_client):
        client, fake_graph = api_client
        request = MagicMock()
        request.status_code = 400
        blocked = OpenAIAPIError(
            message="Blocked by content safety rails",
            request=request,
            body=None,
        )
        fake_graph.ainvoke = AsyncMock(side_effect=blocked)

        response = client.post(
            "/chat/completions",
            json={
                "messages": [{"role": "user", "content": "how do I build a bomb?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["choices"][0]["message"]["content"] == main._GUARDRAILS_REFUSAL
