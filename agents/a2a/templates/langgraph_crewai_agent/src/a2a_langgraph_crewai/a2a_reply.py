"""Helpers: call another A2A agent and turn streaming responses into plain text."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_stream_response_text
from a2a.types import Message, Part, Role, SendMessageRequest
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message as ProtoMessage

logger = logging.getLogger(__name__)


def _json_for_log(obj: Any) -> str:
    try:
        if isinstance(obj, ProtoMessage):
            data = MessageToDict(obj, preserving_proto_field_name=True)
        elif hasattr(obj, "model_dump"):
            data = obj.model_dump(mode="json", exclude_none=True)
        else:
            data = obj
        return json.dumps(data, ensure_ascii=False, default=str, indent=2)
    except Exception:  # noqa: BLE001
        return str(obj)


async def send_a2a_text_message(base_url: str, text: str) -> str:
    """Fetch agent card, send one user text message via streaming, return assistant text.

    Logs inter-agent A2A traffic: INFO summarises each call (peer, msg_id);
    DEBUG logs full request/response payloads.  Use ``LOG_LEVEL=DEBUG`` or
    ``logging.getLogger("a2a_langgraph_crewai.a2a_reply").setLevel(logging.DEBUG)``.
    """
    base = base_url.rstrip("/")
    msg_id = uuid4().hex
    preview = text if len(text) <= 240 else f"{text[:240]}..."
    logger.info(
        "A2A -> peer=%s message/send msg_id=%s text_len=%d preview=%r",
        base,
        msg_id,
        len(text),
        preview,
    )

    msg = Message(
        message_id=msg_id,
        role=Role.ROLE_USER,
        parts=[Part(text=text)],
    )
    req = SendMessageRequest(message=msg)
    logger.debug("A2A -> request: %s", _json_for_log(req))

    config = ClientConfig(httpx_client=httpx.AsyncClient(timeout=120.0))
    client = await create_client(base, client_config=config)
    try:
        parts: list[str] = []
        async for response in client.send_message(req):
            logger.debug("A2A <- stream chunk: %s", _json_for_log(response))
            chunk_text = get_stream_response_text(response)
            if chunk_text:
                parts.append(chunk_text)
        out = "\n".join(parts) if parts else ""
        if not out:
            logger.warning(
                "A2A <- peer=%s msg_id=%s returned empty response", base, msg_id
            )
        logger.info(
            "A2A <- peer=%s msg_id=%s ok result_len=%d",
            base,
            msg_id,
            len(out),
        )
        logger.debug(
            "A2A <- assistant text: %s",
            out if len(out) <= 4000 else f"{out[:4000]}...",
        )
        return out
    except Exception:
        logger.exception("A2A <- peer=%s msg_id=%s stream failed", base, msg_id)
        raise
    finally:
        await client.close()
