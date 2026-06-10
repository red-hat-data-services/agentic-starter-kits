"""Send one message to the LangGraph A2A orchestrator (same pattern as a2a-samples test_client)."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import warnings
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv

# Suppress deprecation on import (A2AClient); must run before a2a imports.
warnings.filterwarnings(
    "ignore",
    message=".*A2AClient is deprecated.*",
    category=DeprecationWarning,
)

from a2a.client import A2ACardResolver, A2AClient  # noqa: E402
from a2a.types import MessageSendParams, SendMessageRequest  # noqa: E402

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    base = os.environ.get("LANGGRAPH_A2A_PUBLIC_URL", "http://127.0.0.1:9200").rstrip(
        "/"
    )
    text = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "Use the specialist tool: in one sentence, what is the A2A protocol?"
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
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
        logger.info("Sending to %s …", base)
        resp = await a2a.send_message(req)
        print(resp.model_dump(mode="json", exclude_none=True))


if __name__ == "__main__":
    asyncio.run(main())
