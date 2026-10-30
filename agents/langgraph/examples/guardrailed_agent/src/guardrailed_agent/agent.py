from os import getenv
from typing import Any

import httpx
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

from guardrailed_agent.tools import check_account_balance

_STAINLESS_RAW_RESPONSE_HEADER = "x-stainless-raw-response"


def strip_stainless_raw_response(request: httpx.Request) -> str | None:
    """Remove the OpenAI SDK raw-response flag from ``request`` headers.

    Returns the previous header value so callers can restore it after send.
    langchain-openai uses ``with_raw_response.create()`` then ``.parse()``;
    that wrapper only works if the SDK still sees this header on the request.
    NeMo Guardrails forwards inbound X-* headers onto its main LLM client, so
    the flag must not go on the wire.
    """
    value = request.headers.get(_STAINLESS_RAW_RESPONSE_HEADER)
    request.headers.pop(_STAINLESS_RAW_RESPONSE_HEADER, None)
    return value


def restore_stainless_raw_response(request: httpx.Request, value: str | None) -> None:
    """Put ``x-stainless-raw-response`` back after the HTTP send."""
    if value is not None:
        request.headers[_STAINLESS_RAW_RESPONSE_HEADER] = value


class _StripRawResponseTransport(httpx.BaseTransport):
    def __init__(self, wrapped: httpx.BaseTransport) -> None:
        self._wrapped = wrapped

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raw = strip_stainless_raw_response(request)
        try:
            return self._wrapped.handle_request(request)
        finally:
            restore_stainless_raw_response(request, raw)

    def close(self) -> None:
        self._wrapped.close()


class _StripRawResponseAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, wrapped: httpx.AsyncBaseTransport) -> None:
        self._wrapped = wrapped

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raw = strip_stainless_raw_response(request)
        try:
            return await self._wrapped.handle_async_request(request)
        finally:
            restore_stainless_raw_response(request, raw)

    async def aclose(self) -> None:
        await self._wrapped.aclose()


def make_nemo_compatible_http_client(**kwargs: Any) -> httpx.Client:
    """httpx client that omits NeMo-incompatible OpenAI SDK headers on the wire."""
    client = DefaultHttpxClient(**kwargs)
    client._transport = _StripRawResponseTransport(client._transport)
    return client


def make_nemo_compatible_async_http_client(**kwargs: Any) -> httpx.AsyncClient:
    """Async httpx client that omits NeMo-incompatible OpenAI SDK headers on the wire."""
    client = DefaultAsyncHttpxClient(**kwargs)
    client._transport = _StripRawResponseAsyncTransport(client._transport)
    return client


def get_graph_closure(
    model_id: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Build and return a LangGraph ReAct agent for banking customer service.

    Creates a ChatOpenAI client, wires check_account_balance tool,
    and uses create_agent to produce a graph that runs the ReAct loop.

    Args:
        model_id: LLM model identifier. Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted.

    Returns:
        A LangGraph agent (CompiledGraph) that accepts {"messages": [...]} and returns updated state.
    """

    if not api_key:
        api_key = getenv("API_KEY")
    if not base_url:
        base_url = getenv("BASE_URL")
    if not model_id:
        model_id = getenv("MODEL_ID")

    if not model_id:
        raise ValueError(
            "MODEL_ID is required. Set it via argument or MODEL_ID env var."
        )

    if not base_url:
        raise ValueError(
            "BASE_URL is required. Set it via argument or BASE_URL env var."
        )
    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])

    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    tools = [check_account_balance]

    # NeMo Guardrails (passthrough) accepts tools only on non-streaming
    # /v1/chat/completions. The playground always sets stream=true, which
    # would otherwise 422: "tools ... only supported for non-streaming
    # requests when ... passthrough: true". disable_streaming keeps the
    # agent's SSE endpoint but sends non-streaming LLM calls to the proxy.
    chat = ChatOpenAI(
        model=model_id,
        temperature=0.01,
        api_key=api_key,
        base_url=base_url,
        disable_streaming=True,
        http_client=make_nemo_compatible_http_client(),
        http_async_client=make_nemo_compatible_async_http_client(),
    )

    system_prompt = """You are a customer service assistant for a retail bank.
        You help customers with account inquiries, billing, payments, and general
        banking questions. For any question about account balances, transactions,
        or account history you MUST call the check_balance tool with the account
        ID the customer provided (for example ACCT-12345). Never invent dollar
        amounts or balances. When you receive a result from a tool, use that
        information to provide a FINAL answer to the customer immediately.
        Do NOT call tools repeatedly for the same question.
        Always be professional and helpful."""
    agent = create_agent(model=chat, tools=tools, system_prompt=system_prompt)

    return agent
