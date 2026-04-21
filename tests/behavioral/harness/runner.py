"""Core task execution engine for agentic evals."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

import httpx


@dataclass
class TaskConfig:
    """Configuration for a single eval task."""

    agent_url: str
    query: str
    expected_tools: list[str] | None = None
    timeout_seconds: float = 30.0
    max_tokens_budget: int | None = None
    model: str | None = None
    stream: bool = False


@dataclass
class TaskResult:
    """Result of running a single eval task."""

    response: str
    tool_calls: list[dict[str, Any]]
    latency_seconds: float
    tokens_used: int | None
    raw_response: dict[str, Any]
    success: bool
    error: str | None = None


def _parse_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    """Parse a single tool call dict into normalized {name, arguments} form."""
    fn = tc.get("function") or {}
    if not isinstance(fn, dict):
        fn = {}
    name = fn.get("name", "")
    raw_args = fn.get("arguments")
    if raw_args is None:
        args = None
    else:
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
    return {"name": name, "arguments": args}


def _extract_tool_calls(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool calls from an OpenAI-compatible chat completion response.

    Checks two locations:
    1. Standard OpenAI format: choices[].message.tool_calls
    2. Agent context field: context[] messages with role=assistant and tool_calls
       (used by agentic-starter-kits agents that expose the full message history)
    """
    tool_calls: list[dict[str, Any]] = []

    # 1. Standard OpenAI location
    choices = response_data.get("choices", [])
    for choice in choices:
        message = choice.get("message", {})
        for tc in message.get("tool_calls", []):
            tool_calls.append(_parse_tool_call(tc))

    if tool_calls:
        return tool_calls

    # 2. Fall back to context field (agentic-starter-kits custom field)
    context = response_data.get("context", [])
    for msg in context:
        if msg.get("role") == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                tool_calls.append(_parse_tool_call(tc))

    return tool_calls


def _extract_response_text(response_data: dict[str, Any]) -> str:
    """Extract the final assistant message text from the response."""
    choices = response_data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "") or ""


def _extract_token_usage(response_data: dict[str, Any]) -> int | None:
    """Extract total token count from the response usage field."""
    usage = response_data.get("usage")
    if usage is None:
        return None
    return usage.get("total_tokens")


async def _run_streaming(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Handle a streaming chat completion request, accumulating the response."""
    collected_content = ""
    collected_tool_calls: list[dict[str, Any]] = []
    usage_data: dict[str, Any] | None = None
    model_name = ""
    parsed_any_chunk = False
    malformed_count = 0

    async with client.stream(
        "POST", url, json=payload, timeout=timeout
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                parsed_any_chunk = True
            except json.JSONDecodeError:
                malformed_count += 1
                logger.warning("Malformed SSE chunk (not valid JSON): %s", data_str[:200])
                continue

            if not model_name:
                model_name = chunk.get("model", "")

            if "usage" in chunk:
                usage_data = chunk["usage"]

            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                if "content" in delta and delta["content"]:
                    collected_content += delta["content"]
                for tc in delta.get("tool_calls", []):
                    idx = tc.get("index", 0)
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append(
                            {"function": {"name": "", "arguments": ""}}
                        )
                    fn = tc.get("function", {})
                    if "name" in fn:
                        collected_tool_calls[idx]["function"]["name"] = fn["name"]
                    if "arguments" in fn and fn["arguments"] is not None:
                        arg_chunk = fn["arguments"]
                        collected_tool_calls[idx]["function"]["arguments"] += (
                            arg_chunk if isinstance(arg_chunk, str) else json.dumps(arg_chunk)
                        )

    if not parsed_any_chunk and malformed_count > 0:
        raise ValueError(
            f"All {malformed_count} SSE chunks were malformed JSON — "
            "agent response is not valid"
        )

    # Reconstruct a non-streaming-style response dict
    message: dict[str, Any] = {"role": "assistant", "content": collected_content}
    if collected_tool_calls:
        message["tool_calls"] = [
            {"type": "function", "function": tc["function"]}
            for tc in collected_tool_calls
        ]

    result: dict[str, Any] = {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "model": model_name,
    }
    if usage_data:
        result["usage"] = usage_data
    return result


async def run_task(
    config: TaskConfig,
    client: httpx.AsyncClient | None = None,
) -> TaskResult:
    """Execute a single eval task against an agent endpoint.

    Sends the query to the agent's /chat/completions endpoint,
    measures latency, extracts tool calls and token usage.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    url = f"{config.agent_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": config.query}],
    }
    if config.model:
        payload["model"] = config.model
    if config.stream:
        payload["stream"] = True

    start = time.monotonic()
    try:
        if config.stream:
            response_data = await _run_streaming(
                client, url, payload, config.timeout_seconds
            )
        else:
            resp = await client.post(
                url, json=payload, timeout=config.timeout_seconds
            )
            resp.raise_for_status()
            response_data = resp.json()

        latency = time.monotonic() - start
        tool_calls = _extract_tool_calls(response_data)
        response_text = _extract_response_text(response_data)
        tokens_used = _extract_token_usage(response_data)

        return TaskResult(
            response=response_text,
            tool_calls=tool_calls,
            latency_seconds=latency,
            tokens_used=tokens_used,
            raw_response=response_data,
            success=True,
        )

    except httpx.HTTPStatusError as exc:
        latency = time.monotonic() - start
        return TaskResult(
            response="",
            tool_calls=[],
            latency_seconds=latency,
            tokens_used=None,
            raw_response={"error": str(exc)},
            success=False,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
        )
    except (json.JSONDecodeError, ValueError) as exc:
        latency = time.monotonic() - start
        return TaskResult(
            response="",
            tool_calls=[],
            latency_seconds=latency,
            tokens_used=None,
            raw_response={"error": str(exc)},
            success=False,
            error=f"Invalid JSON from agent response: {str(exc)[:200]}",
        )
    except (httpx.RequestError, TimeoutError) as exc:
        latency = time.monotonic() - start
        return TaskResult(
            response="",
            tool_calls=[],
            latency_seconds=latency,
            tokens_used=None,
            raw_response={"error": str(exc)},
            success=False,
            error=str(exc),
        )
    finally:
        if own_client:
            await client.aclose()
