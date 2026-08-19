"""Unit tests for the ChatOpenAI client used against NeMo Guardrails."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import httpx
from guardrailed_agent.agent import (
    get_graph_closure,
    make_nemo_compatible_async_http_client,
    make_nemo_compatible_http_client,
    strip_stainless_raw_response,
)
from langchain_openai import ChatOpenAI


def _request_with_stainless_headers() -> httpx.Request:
    return httpx.Request(
        "POST",
        "http://guardrails.svc/v1/chat/completions",
        headers={
            "authorization": "Bearer test-key",
            "x-stainless-lang": "python",
            "x-stainless-raw-response": "true",
        },
    )


def _completion_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello from the bank."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        },
    )


class TestStripStainlessRawResponse:
    def test_removes_raw_response_flag(self):
        request = _request_with_stainless_headers()

        strip_stainless_raw_response(request)

        assert "x-stainless-raw-response" not in request.headers

    def test_keeps_other_headers(self):
        request = _request_with_stainless_headers()

        strip_stainless_raw_response(request)

        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["x-stainless-lang"] == "python"

    def test_noop_when_header_absent(self):
        request = httpx.Request(
            "POST",
            "http://guardrails.svc/v1/chat/completions",
            headers={"content-type": "application/json"},
        )

        strip_stainless_raw_response(request)

        assert request.headers["content-type"] == "application/json"


class TestNemoCompatibleHttpClient:
    def test_sync_client_strips_header_on_the_wire(self):
        captured: dict[str, httpx.Headers] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = httpx.Headers(request.headers)
            return httpx.Response(200, json={"ok": True})

        client = make_nemo_compatible_http_client(
            transport=httpx.MockTransport(handler)
        )
        with client:
            client.post(
                "http://guardrails.svc/v1/chat/completions",
                headers={
                    "x-stainless-raw-response": "true",
                    "x-stainless-lang": "python",
                },
            )

        assert "x-stainless-raw-response" not in captured["headers"]
        assert captured["headers"]["x-stainless-lang"] == "python"

    def test_async_client_strips_header_on_the_wire(self):
        captured: dict[str, httpx.Headers] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = httpx.Headers(request.headers)
            return httpx.Response(200, json={"ok": True})

        async def _post() -> None:
            client = make_nemo_compatible_async_http_client(
                transport=httpx.MockTransport(handler)
            )
            await client.post(
                "http://guardrails.svc/v1/chat/completions",
                headers={"x-stainless-raw-response": "true"},
            )
            await client.aclose()

        asyncio.run(_post())

        assert "x-stainless-raw-response" not in captured["headers"]

    def test_chat_openai_ainvoke_still_parses_when_header_stripped_on_wire(self):
        """langchain-openai calls with_raw_response.create() then .parse().

        The header must leave the agent (NeMo forwards X-* onto its LLM client)
        but remain visible to the OpenAI SDK so parse() is not called on a
        plain ChatCompletion.
        """
        captured: dict[str, httpx.Headers] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = httpx.Headers(request.headers)
            return _completion_response()

        chat = ChatOpenAI(
            model="test-model",
            api_key="test-key",
            base_url="http://guardrails.svc/v1",
            http_client=make_nemo_compatible_http_client(
                transport=httpx.MockTransport(handler)
            ),
            http_async_client=make_nemo_compatible_async_http_client(
                transport=httpx.MockTransport(handler)
            ),
        )

        result = asyncio.run(chat.ainvoke("Hello"))

        assert "Hello from the bank." in result.content
        assert "x-stainless-raw-response" not in captured["headers"]


class TestGetGraphClosureHttpClients:
    def test_chat_openai_receives_nemo_compatible_clients(self):
        with (
            patch("guardrailed_agent.agent.ChatOpenAI") as mock_chat,
            patch("guardrailed_agent.agent.create_agent") as mock_create,
        ):
            mock_chat.return_value = MagicMock()
            mock_create.return_value = MagicMock(name="graph")

            get_graph_closure(
                model_id="qwen2-5-7b-instruct",
                base_url="http://localhost:8090/v1",
                api_key="test-key",
            )

        kwargs = mock_chat.call_args.kwargs
        assert isinstance(kwargs["http_client"], httpx.Client)
        assert isinstance(kwargs["http_async_client"], httpx.AsyncClient)
        prompt = mock_create.call_args.kwargs["system_prompt"]
        assert "check_balance" in prompt
        assert "Never invent dollar" in prompt
