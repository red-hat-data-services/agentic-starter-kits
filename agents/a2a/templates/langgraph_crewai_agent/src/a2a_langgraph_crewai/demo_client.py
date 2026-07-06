"""Send one message to the LangGraph A2A orchestrator (same pattern as a2a-samples test_client)."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from uuid import uuid4

from a2a.client import create_client
from a2a.helpers import get_stream_response_text
from a2a.types import Message, Part, Role, SendMessageRequest
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

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

    logger.info("Sending to %s ...", base)
    msg = Message(
        message_id=uuid4().hex,
        role=Role.ROLE_USER,
        parts=[Part(text=text)],
    )
    req = SendMessageRequest(message=msg)
    client = await create_client(base)
    try:
        async for response in client.send_message(req):
            resp_text = get_stream_response_text(response)
            if resp_text:
                print(resp_text)
            else:
                print(MessageToDict(response, preserving_proto_field_name=True))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
