"""Helpers: call another A2A agent and turn SendMessageResponse into plain text."""

from __future__ import annotations

import json
import logging
import warnings
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    JSONRPCErrorResponse,
    Message,
    MessageSendParams,
    SendMessageRequest,
    Task,
)
from a2a.utils import get_artifact_text, get_message_text

logger = logging.getLogger(__name__)

# Legacy client is still the simplest JSON-RPC surface used in a2a-samples.
warnings.filterwarnings(
    "ignore",
    message=".*A2AClient is deprecated.*",
    category=DeprecationWarning,
)


def _unwrap_send_result(response: Any) -> Any:
    root = response.root
    if isinstance(root, JSONRPCErrorResponse):
        raise RuntimeError(f"A2A JSON-RPC error: {root.error}")
    return root.result


def a2a_result_to_text(result: Message | Task | Any) -> str:
    if isinstance(result, Message):
        return get_message_text(result)
    if isinstance(result, Task):
        chunks: list[str] = []
        if result.artifacts:
            for art in result.artifacts:
                chunks.append(get_artifact_text(art))
        if chunks:
            return "\n".join(chunks)
        if result.status and result.status.message:
            return get_message_text(result.status.message)
        return str(result)
    return str(result)


def _json_for_log(obj: Any) -> str:
    try:
        if hasattr(obj, "model_dump"):
            data = obj.model_dump(mode="json", exclude_none=True)
        else:
            data = obj
        return json.dumps(data, ensure_ascii=False, default=str, indent=2)
    except Exception:  # noqa: BLE001
        return str(obj)


async def send_a2a_text_message(
    base_url: str, text: str, timeout: float = 120.0
) -> str:
    """Fetch agent card, send one user text message, return assistant text.

    Logs inter-agent A2A traffic: INFO summarizes each call (peer, JSON-RPC id);
    DEBUG logs full ``SendMessageRequest`` / response payloads (same objects the client
    serializes over JSON-RPC). Use ``LOG_LEVEL=DEBUG`` or ``logging.getLogger("a2a_langgraph_crewai.a2a_reply").setLevel(logging.DEBUG)``.
    """
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        resolver = A2ACardResolver(httpx_client=client, base_url=base)
        card = await resolver.get_agent_card()
        a2a = A2AClient(httpx_client=client, agent_card=card)
        payload: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": uuid4().hex,
            },
        }
        req = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(**payload),
        )
        preview = text if len(text) <= 240 else f"{text[:240]}…"
        logger.info(
            "A2A → peer=%s JSON-RPC message/send id=%s text_len=%d preview=%r",
            base,
            req.id,
            len(text),
        )
        logger.debug("A2A → prompt preview: %r", preview)
        logger.debug("A2A → request (message/send params): %s", _json_for_log(req))

        try:
            resp = await a2a.send_message(req)
        except Exception:
            logger.exception("A2A ← peer=%s message/send failed (id=%s)", base, req.id)
            raise

        logger.debug("A2A ← raw response object: %s", _json_for_log(resp))

        result = _unwrap_send_result(resp)
        out = a2a_result_to_text(result)
        logger.info(
            "A2A ← peer=%s id=%s ok result_len=%d",
            base,
            req.id,
            len(out),
        )
        logger.debug(
            "A2A ← assistant text: %s", out if len(out) <= 4000 else f"{out[:4000]}…"
        )
        return out
