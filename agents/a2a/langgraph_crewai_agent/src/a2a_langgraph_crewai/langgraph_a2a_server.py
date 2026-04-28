"""
LangGraph ReAct-style orchestrator exposed as A2A; delegates to the CrewAI A2A agent via tool.

Run (after crew): uv run python -m a2a_langgraph_crewai.langgraph_a2a_server
OpenShift: PORT=8080; set CREW_A2A_URL to the in-cluster Service URL (e.g. http://a2a-crew-agent:8080).

Playground: GET / serves a chat UI that calls POST / with JSON-RPC message/send (same as demo_client).
POST /chat/completions remains available as an OpenAI-compatible shim for other clients.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from os import getenv
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    MessageSendParams,
    SendMessageRequest,
)
from a2a.utils import new_agent_text_message
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from .a2a_reply import send_a2a_text_message

load_dotenv()
_log_level = getattr(
    logging,
    getenv("LOG_LEVEL", "INFO").upper(),
    logging.INFO,
)
logging.basicConfig(level=_log_level)
logger = logging.getLogger(__name__)

_graph = None

_PKG_DIR = Path(__file__).resolve().parent
_PLAYGROUND_HTML = _PKG_DIR / "playground" / "templates" / "index.html"
_IMAGES_DIR = _PKG_DIR / "images"


def _listen_port() -> int:
    if p := getenv("PORT"):
        return int(p)
    return int(getenv("LANGGRAPH_A2A_PORT", "9200"))


def _crew_base_url() -> str:
    return getenv("CREW_A2A_URL", "http://127.0.0.1:9100").rstrip("/")


def _normalize_openai_base_url(base_url: str) -> str:
    """Match crew_a2a_server + react_agent: OpenAI-compatible chat is under .../v1/chat/completions."""
    u = base_url.strip().rstrip("/")
    if not u.endswith("/v1"):
        u = f"{u}/v1"
    return u


@tool
async def ask_crew_specialist(question: str) -> str:
    """Ask the remote CrewAI A2A specialist for a detailed answer. Use for harder or domain-specific questions."""
    return await send_a2a_text_message(_crew_base_url(), question)


def _build_graph():
    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")
    api_key = getenv("API_KEY") or "no-key"
    if not base_url or not model_id:
        raise RuntimeError("BASE_URL and MODEL_ID must be set (see template.env).")

    base_url = _normalize_openai_base_url(base_url)
    logger.info("ChatOpenAI base_url (normalized)=%s", base_url)

    is_local = any(h in base_url for h in ("localhost", "127.0.0.1"))
    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local BASE_URL.")

    chat = ChatOpenAI(
        model=model_id,
        temperature=0.01,
        api_key=api_key,
        base_url=base_url,
    )
    system_prompt = (
        "You are the orchestrator. Answer simple questions yourself. "
        "For deeper or specialized questions, call ask_crew_specialist once, "
        "then summarize the final answer for the user."
    )
    return create_agent(
        model=chat,
        tools=[ask_crew_specialist],
        system_prompt=system_prompt,
    )


def _ensure_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def _single_ai_text(message: AIMessage) -> str:
    """String content from one AIMessage (handles string or structured content blocks)."""
    c = message.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts) if parts else str(c)
    return str(c) if c else ""


def _last_ai_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return _single_ai_text(m)
    return ""


def _make_completion_id() -> str:
    return f"chatcmpl-{uuid4().hex[:12]}"


async def run_orchestrator(user_text: str) -> str:
    """Shared invoke used by A2A executor and OpenAI-compatible playground."""
    graph = _ensure_graph()
    out = await graph.ainvoke({"messages": [HumanMessage(content=user_text)]})
    messages = out.get("messages", [])
    return _last_ai_text(messages) or str(out)


def _jsonrpc_message_send_envelope(user_text: str) -> dict[str, Any]:
    """Same JSON-RPC body shape as demo_client / A2AClient.send_message (method message/send, POST /)."""
    msg_id = uuid4().hex
    req_id = str(uuid4())
    payload = {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": user_text}],
            "messageId": msg_id,
        },
    }
    send_req = SendMessageRequest(
        id=req_id,
        params=MessageSendParams(**payload),
    )
    return send_req.model_dump(mode="json", exclude_none=True)


def _jsonrpc_ok_envelope(request_id: str, assistant_text: str) -> dict[str, Any]:
    """Readable success trace; full A2A result objects can include tasks, artifacts, and SSE metadata."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "_note": "Simplified playground trace; full A2A responses may include tasks, artifacts, etc.",
            "assistantMessage": {
                "parts": [{"kind": "text", "text": assistant_text}],
            },
        },
    }


def _stream_chunk_text(raw: Any) -> str:
    """Normalize LangChain stream chunk content to a string."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(raw)


def _tool_call_to_delta(tc: Any, index: int) -> dict[str, Any]:
    if isinstance(tc, dict):
        tid = tc.get("id", "")
        name = tc.get("name", "")
        args = tc.get("args", {})
    else:
        tid = getattr(tc, "id", "") or ""
        name = getattr(tc, "name", "") or ""
        args = getattr(tc, "args", {}) or {}
    return {
        "index": index,
        "id": tid,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args) if not isinstance(args, str) else args,
        },
    }


async def _stream_orchestrator_sse(
    user_text: str,
    rpc_req: dict[str, Any],
    req_id: str,
) -> AsyncIterator[str]:
    """Stream OpenAI `chat.completion.chunk` SSE lines, then A2A JSON-RPC trace and `[DONE]`."""
    graph = _ensure_graph()
    model_id = getenv("MODEL_ID", "unknown")
    completion_id = _make_completion_id()
    created = int(time.time())
    final_reply = ""
    streamed_token_parts: list[str] = []

    yield f"data: {json.dumps({'object': 'a2a.protocol', 'phase': 'jsonrpc_request', 'payload': rpc_req})}\n\n"

    try:
        async for event in graph.astream_events(
            {"messages": [HumanMessage(content=user_text)]},
            config={"recursion_limit": 15},
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                text = _stream_chunk_text(getattr(chunk, "content", None))
                if text:
                    streamed_token_parts.append(text)
                    data = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_id,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": text},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(data)}\n\n"
            elif kind == "on_chat_model_end":
                message = event["data"]["output"]
                if isinstance(message, AIMessage):
                    t = _single_ai_text(message)
                    if t.strip():
                        final_reply = t
                    tool_calls = getattr(message, "tool_calls", None) or []
                    if tool_calls:
                        tool_calls_delta = [
                            _tool_call_to_delta(tc, i)
                            for i, tc in enumerate(tool_calls)
                        ]
                        data = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_id,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "tool_calls": tool_calls_delta,
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(data)}\n\n"
            elif kind == "on_tool_end":
                output = event["data"].get("output", "")
                if hasattr(output, "content"):
                    output = output.content
                data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_id,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "tool",
                                "content": str(output),
                                "name": event.get("name", ""),
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(data)}\n\n"

        if not final_reply.strip() and streamed_token_parts:
            final_reply = "".join(streamed_token_parts)
        if not final_reply.strip():
            out = await graph.ainvoke(
                {"messages": [HumanMessage(content=user_text)]},
                config={"recursion_limit": 15},
            )
            final_reply = _last_ai_text(out.get("messages", [])) or str(out)

        rpc_resp = _jsonrpc_ok_envelope(req_id, final_reply)
        yield f"data: {json.dumps({'object': 'a2a.protocol', 'phase': 'jsonrpc_response', 'payload': rpc_resp, 'hint': 'A2A JSON-RPC over POST / (same method message/send as demo_client / a2a-sdk).'})}\n\n"
        final_data = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_data)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:  # noqa: BLE001
        logger.exception("Playground stream failed")
        err = {"error": {"message": str(e), "type": "server_error"}}
        yield f"data: {json.dumps(err)}\n\n"
        yield "data: [DONE]\n\n"


class LangGraphA2AExecutor(AgentExecutor):
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        user = context.get_user_input()
        if not user.strip():
            await event_queue.enqueue_event(
                new_agent_text_message("Error: empty user message.")
            )
            return
        try:
            reply = await run_orchestrator(user)
            await event_queue.enqueue_event(new_agent_text_message(reply))
        except Exception as e:  # noqa: BLE001
            logger.exception("LangGraph invoke failed")
            await event_queue.enqueue_event(
                new_agent_text_message(f"LangGraph error: {e!s}")
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported in this demo")


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            return str(c)
    return ""


async def _playground_page(_request: Request) -> FileResponse:
    if not _PLAYGROUND_HTML.is_file():
        raise HTTPException(status_code=404, detail="Playground template missing.")
    return FileResponse(_PLAYGROUND_HTML)


async def _health(_request: Request) -> JSONResponse:
    try:
        _ensure_graph()
    except Exception:
        return JSONResponse(
            {"status": "unhealthy", "agent_initialized": False},
            status_code=503,
        )
    return JSONResponse({"status": "healthy", "agent_initialized": True})


async def _serve_image(request: Request) -> FileResponse:
    filename = request.path_params["filename"]
    base = _IMAGES_DIR.resolve()
    file_path = (base / filename).resolve()
    try:
        file_path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(file_path)


async def _chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    messages = body.get("messages") or []
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")
    stream = bool(body.get("stream", False))
    user_text = _last_user_text(messages)
    if not user_text.strip():
        raise HTTPException(status_code=400, detail="No user message in messages")

    rpc_req = _jsonrpc_message_send_envelope(user_text)
    req_id = rpc_req["id"]

    if stream:
        return StreamingResponse(
            _stream_orchestrator_sse(user_text, rpc_req, req_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        reply = await run_orchestrator(user_text)
    except Exception as e:  # noqa: BLE001
        logger.exception("Playground invoke failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    rpc_resp = _jsonrpc_ok_envelope(req_id, reply)
    return JSONResponse(
        {
            "id": "chatcmpl-a2a-playground",
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": reply}}
            ],
            "a2a_protocol": {
                "jsonrpc_request": rpc_req,
                "jsonrpc_response": rpc_resp,
            },
        }
    )


def _build_starlette_app(
    agent_card: AgentCard, handler: DefaultRequestHandler
) -> Starlette:
    a2a_factory = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    playground_routes = [
        Route("/", _playground_page, methods=["GET"]),
        Route("/health", _health, methods=["GET"]),
        Route("/chat/completions", _chat_completions, methods=["POST"]),
        Route("/images/{filename:path}", _serve_image, methods=["GET"]),
    ]
    return Starlette(routes=playground_routes + list(a2a_factory.routes()))


def main() -> None:
    public_base = getenv("LANGGRAPH_A2A_PUBLIC_URL", "http://127.0.0.1:9200").rstrip(
        "/"
    )
    port = _listen_port()

    skill = AgentSkill(
        id="langgraph_orchestrator",
        name="LangGraph orchestrator",
        description="ReAct-style agent that can delegate to a CrewAI peer over A2A.",
        tags=["langgraph", "text", "a2a"],
        examples=[
            "What is 2+2?",
            "Ask the specialist to explain agent-to-agent protocols.",
        ],
    )

    agent_card = AgentCard(
        name="LangGraph A2A Orchestrator",
        description="LangGraph agent using A2A JSON-RPC to call a CrewAI specialist.",
        url=f"{public_base}/",
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
        supports_authenticated_extended_card=False,
    )

    handler = DefaultRequestHandler(
        agent_executor=LangGraphA2AExecutor(),
        task_store=InMemoryTaskStore(),
    )
    app = _build_starlette_app(agent_card, handler)
    logger.info(
        "LangGraph A2A listening on 0.0.0.0:%s (crew peer=%s); playground GET /",
        port,
        _crew_base_url(),
    )
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
