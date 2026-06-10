import asyncio
import json
import logging
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from autogen_agent_base.agent import get_agent_chat
from autogen_agent_base.tracing import enable_tracing
from autogen_agentchat.base._task import TaskResult
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    TextMessage,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
    ToolCallSummaryMessage,
)
from autogen_core import CancellationToken
from autogen_ext.tools.mcp import (
    SseServerParams,
    create_mcp_server_session,
    mcp_server_tools,
)
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field, model_validator

load_dotenv()


class ChatMessage(BaseModel):
    """A message in the conversation."""

    role: str = Field(
        ...,
        description="The role of the message author.",
        examples=["user", "assistant", "system"],
    )
    content: str = Field(
        ...,
        description="The contents of the message.",
        examples=["What is 17 + 25? Use your tools to compute it."],
    )


class ChatRequest(BaseModel):
    """Creates a model response for the given chat conversation (MCP-backed AutoGen agent).

    [See OpenAI chat docs](https://platform.openai.com/docs/api-reference/chat/create)
    """

    message: str | None = Field(
        None,
        description=(
            "Single user message (shortcut). Ignored if `messages` is set. "
            "Either this or `messages` with at least one user turn is required."
        ),
    )
    messages: list[ChatMessage] | None = Field(
        None,
        description="A list of messages comprising the conversation so far; last user message is used as the task.",
    )
    stream: bool = Field(
        False,
        description=(
            "If true, partial message deltas are sent as SSE `data: {json}\\n\\n` events "
            "(object `chat.completion.chunk`), terminated by `data: [DONE]\\n\\n`."
        ),
    )

    @model_validator(mode="after")
    def _need_user_input(self):
        if self.messages:
            if not any(m.role == "user" for m in self.messages):
                raise ValueError("messages must include at least one role=user entry")
            return self
        if self.message is not None and self.message != "":
            return self
        raise ValueError("Provide non-empty `message` or `messages` with a user turn")

    def user_task(self) -> str:
        if self.messages:
            for m in reversed(self.messages):
                if m.role == "user":
                    return m.content
        return self.message or ""


class ChatResponse(BaseModel):
    """Non-streaming response: simplified chat turns (not full OpenAI `chat.completion` object)."""

    messages: list[dict] = Field(
        ...,
        description="Conversation turns (`role` / `content`); last entry is the assistant reply.",
    )
    finish_reason: str = Field(
        ...,
        description="Why generation stopped.",
        examples=["stop"],
    )
    tool_invocations: list[dict] = Field(
        default_factory=list,
        description=(
            "MCP tools used in this turn: each entry has `name`, `arguments`, `result` (truncated), "
            "`is_error` if applicable."
        ),
    )


class HealthResponse(BaseModel):
    """Service health: HTTP 200 when the agent is ready; 503 until MCP-backed agent initialized."""

    status: str = Field(
        ...,
        description="`healthy` when ready, `not_ready` when initialization is incomplete or failed.",
        examples=["healthy"],
    )
    agent_initialized: bool = Field(
        ...,
        description="Whether the AutoGen agent connected to MCP and is ready to serve `/chat/completions`.",
    )


MCP_SYSTEM_PROMPT = (
    "You are a helpful assistant. Your goal is to answer the user's question directly in every interaction. "
    "ONLY call a tool if you cannot answer with your own knowledge or if external/up-to-date information is required. "
    "If you call a tool and receive a response, extract the relevant answer and present it as your FINAL answer to the user. "
    "Never call tools more than once for the same user question. Be polite, concise, and accurate in every reply."
)


async def _mcp_agent_holder(
    app: FastAPI, shutdown_event: asyncio.Event, ready_event: asyncio.Event
):
    """Hold MCP session and AutoGen agent; signal when ready, wait until shutdown."""
    mcp_url = getenv("MCP_SERVER_URL")
    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")
    api_key = getenv("API_KEY", "")
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    logger = logging.getLogger(__name__)
    server_params = SseServerParams(url=mcp_url, timeout=60, sse_read_timeout=300)
    try:
        async with create_mcp_server_session(server_params) as session:
            await session.initialize()
            tools = await mcp_server_tools(server_params=server_params, session=session)
            get_agent = get_agent_chat(
                model_id=model_id,
                base_url=base_url,
                api_key=api_key,
                tools=tools,
            )
            agent = get_agent(system_prompt=MCP_SYSTEM_PROMPT)
            app.state.mcp_agent = agent
            ready_event.set()
            await shutdown_event.wait()
    except Exception as e:
        app.state.mcp_agent = None
        logger.exception("MCP agent init failed: %s", e)
        traceback.print_exception(type(e), e, e.__traceback__)
        app.state.mcp_agent_error = str(e)
        ready_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to MCP server, build AutoGen agent with MCP tools, keep connection until shutdown."""
    enable_tracing()

    app.state.mcp_agent = None
    app.state.mcp_agent_error = None
    shutdown_event = asyncio.Event()
    ready_event = asyncio.Event()
    task = asyncio.create_task(_mcp_agent_holder(app, shutdown_event, ready_event))
    try:
        await asyncio.wait_for(ready_event.wait(), timeout=60.0)
    except asyncio.TimeoutError:
        app.state.mcp_agent_error = "MCP connection timeout"
    yield
    shutdown_event.set()
    await asyncio.wait_for(task, timeout=10.0)


app = FastAPI(
    title="AutoGen Agent (MCP) API",
    description=(
        "FastAPI service for an AutoGen AssistantAgent with MCP tools over SSE, "
        "with an OpenAI-compatible `POST /chat/completions` API. "
        "When `stream=false`, returns JSON with `messages` and `finish_reason`. "
        "When `stream=true`, returns Server-Sent Events with `chat.completion.chunk` deltas. "
        "Open `GET /` for an interactive playground."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Chat", "description": "Chat completion operations"},
        {"name": "Health", "description": "Service health monitoring"},
    ],
)


def _assistant_content_from_result(result) -> str:
    if not result.messages:
        return ""
    last = result.messages[-1]
    if isinstance(last, TextMessage):
        return last.content or ""
    return getattr(last, "content", None) or str(last)


_MAX_TOOL_RESULT_CHARS = 2000


def _truncate_tool_result(text: str) -> str:
    if len(text) > _MAX_TOOL_RESULT_CHARS:
        return text[:_MAX_TOOL_RESULT_CHARS] + "…"
    return text


def _invocation_row(call, res) -> dict:
    """Pair FunctionCall + FunctionExecutionResult for API / playground."""
    args_raw = getattr(call, "arguments", "") or ""
    try:
        args_out: str | dict | list = json.loads(args_raw) if args_raw.strip() else {}
    except json.JSONDecodeError:
        args_out = args_raw
    content = (getattr(res, "content", None) or "") or ""
    return {
        "name": getattr(call, "name", "") or "",
        "arguments": args_out,
        "result": _truncate_tool_result(str(content)),
        "is_error": bool(getattr(res, "is_error", False)),
    }


def _invocation_row_result_only(res) -> dict:
    content = (getattr(res, "content", None) or "") or ""
    return {
        "name": getattr(res, "name", "") or "",
        "arguments": None,
        "result": _truncate_tool_result(str(content)),
        "is_error": bool(getattr(res, "is_error", False)),
    }


def _invocations_from_tool_summary(msg: ToolCallSummaryMessage) -> list[dict]:
    rows: list[dict] = []
    calls = msg.tool_calls or []
    results = msg.results or []
    for i, call in enumerate(calls):
        res = results[i] if i < len(results) else None
        if res is not None:
            rows.append(_invocation_row(call, res))
    return rows


def _tool_invocations_from_task_messages(messages) -> list[dict]:
    """Collect tool rows from AssistantAgent stream/run messages.

    With ``reflect_on_tool_use=True`` (default), tools appear as
    ``ToolCallRequestEvent`` + ``ToolCallExecutionEvent``, not ``ToolCallSummaryMessage``.
    """
    out: list[dict] = []
    last_request_calls: list | None = None

    for m in messages or []:
        if isinstance(m, ToolCallRequestEvent):
            last_request_calls = list(m.content)
        elif isinstance(m, ToolCallExecutionEvent):
            results = list(m.content or [])
            if last_request_calls and len(last_request_calls) == len(results):
                for call, res in zip(last_request_calls, results):
                    out.append(_invocation_row(call, res))
            elif last_request_calls:
                by_id = {
                    getattr(c, "id", ""): c
                    for c in last_request_calls
                    if getattr(c, "id", None)
                }
                for res in results:
                    cid = getattr(res, "call_id", "") or ""
                    call = by_id.get(cid)
                    if call is not None:
                        out.append(_invocation_row(call, res))
                    else:
                        out.append(_invocation_row_result_only(res))
            else:
                for res in results:
                    out.append(_invocation_row_result_only(res))
            last_request_calls = None
        elif isinstance(m, ToolCallSummaryMessage):
            out.extend(_invocations_from_tool_summary(m))

    return out


@app.post(
    "/chat/completions",
    response_model=ChatResponse,
    summary="Create chat completion",
    description=(
        "Creates a model response for the given chat conversation. "
        "When `stream=false`, returns a complete JSON object with `messages` and `finish_reason`. "
        "When `stream=true`, returns Server-Sent Events with `chat.completion.chunk` deltas. "
        "If any MCP tools run, an extra event with `object`: `mcp.tool_usage` is sent before `[DONE]` "
        "(extension to OpenAI streaming; clients can ignore it)."
    ),
    tags=["Chat"],
)
async def chat(request: ChatRequest):
    agent = getattr(app.state, "mcp_agent", None)
    if agent is None:
        err = (
            getattr(app.state, "mcp_agent_error", None)
            or "Agent not initialized (MCP connection failed or not ready)"
        )
        raise HTTPException(status_code=503, detail=err)

    user_text = request.user_task()
    model_id = getenv("MODEL_ID") or "model"

    if request.stream:

        async def event_generator():
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(time.time())
            cancel_token = CancellationToken()
            logger = logging.getLogger(__name__)
            try:
                stream_tools: list[dict] = []
                async for ev in agent.run_stream(
                    task=user_text,
                    cancellation_token=cancel_token,
                ):
                    if isinstance(ev, TaskResult):
                        stream_tools = _tool_invocations_from_task_messages(ev.messages)
                        continue
                    if isinstance(ev, ModelClientStreamingChunkEvent) and ev.content:
                        data = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_id,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": ev.content},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(data)}\n\n"

                if stream_tools:
                    yield f"data: {json.dumps({'object': 'mcp.tool_usage', 'tools': stream_tools})}\n\n"

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
            except Exception:
                logger.exception("Error in stream event_generator")
                err = {
                    "error": {
                        "message": "Internal server error",
                        "type": "server_error",
                    }
                }
                yield f"data: {json.dumps(err)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        cancel_token = CancellationToken()
        result = await agent.run(
            task=user_text,
            cancellation_token=cancel_token,
        )
        response_messages = [{"role": "user", "content": user_text}]
        content = _assistant_content_from_result(result)
        response_messages.append({"role": "assistant", "content": content})
        tools_used = _tool_invocations_from_task_messages(result.messages)
        return ChatResponse(
            messages=response_messages,
            finish_reason="stop",
            tool_invocations=tools_used,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {e!s}"
        ) from e


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Returns 200 when the MCP-backed agent is ready; 503 with `not_ready` until initialization completes "
        "so Kubernetes readiness probes can hold traffic until the service is usable."
    ),
    tags=["Health"],
)
async def health():
    agent_initialized = getattr(app.state, "mcp_agent", None) is not None
    body = {
        "status": "healthy" if agent_initialized else "not_ready",
        "agent_initialized": agent_initialized,
    }
    if not agent_initialized:
        return JSONResponse(status_code=503, content=body)
    return body


# ── Playground UI ────────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parent
_PLAYGROUND_HTML = _BASE_DIR / "playground" / "templates" / "index.html"
_IMAGES_DIR = _BASE_DIR / "images"
if not _IMAGES_DIR.is_dir():
    _IMAGES_DIR = _BASE_DIR.parent.parent.parent / "images"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def playground():
    """Serve the playground chat UI."""
    return FileResponse(_PLAYGROUND_HTML)


@app.get("/images/{filename:path}", include_in_schema=False)
async def serve_image(filename: str):
    """Serve images from the project-level images directory."""
    base = _IMAGES_DIR.resolve()
    file_path = (base / filename).resolve()
    try:
        file_path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=404, detail="Image not found") from None
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path)


if __name__ == "__main__":
    import uvicorn

    port = int(getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
