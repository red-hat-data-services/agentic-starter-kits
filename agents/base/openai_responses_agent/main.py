import asyncio
import json
import logging
from contextlib import asynccontextmanager
from os import getenv

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai_responses_agent_base.agent import get_agent_closure, AIAgent
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Request/Response models
class ChatRequest(BaseModel):
    """Incoming chat request body for the /chat endpoint."""

    message: str


class ChatResponse(BaseModel):
    """Structured chat response (answer and optional steps)."""

    answer: str
    steps: list[str]


# Global variable for agent factory (get_agent callable)
get_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent closure on startup and clear it on shutdown.

    Reads BASE_URL and MODEL_ID from the environment and sets the global get_agent
    for the /chat endpoint. Uses OpenAI client and Responses API (no agentic framework).
    """
    global get_agent

    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")

    # Ensure base_url ends with /v1 if provided
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    get_agent = get_agent_closure(base_url=base_url, model_id=model_id)

    yield

    get_agent = None


app = FastAPI(
    title="OpenAI Responses Agent API",
    description="FastAPI service for agent (OpenAI client + pure Python, Responses API, no agentic framework)",
    lifespan=lifespan,
)


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint that accepts a message and returns the agent's response.

    Returns:
        JSON response with full conversation history (same format as LangGraph/LlamaIndex agents).
    """
    global get_agent

    if get_agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        agent = get_agent()
        messages = [{"role": "user", "content": request.message}]

        result = await agent.run(input=messages)

        return result["messages"]

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


@app.post("/stream")
async def stream(request: ChatRequest):
    """
    Streaming chat endpoint that accepts a message and returns the agent's
    response as Server-Sent Events (SSE).

    Event types:
        - tool_call: tool invocation by the agent
        - tool_result: result returned by a tool (observation)
        - token: final answer text
        - done: signals the stream is complete

    Args:
        request: ChatRequest containing the user message
    """
    global get_agent

    if get_agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    async def event_generator():
        try:
            queue: asyncio.Queue = asyncio.Queue()

            def on_event(event_type: str, data: dict):
                queue.put_nowait((event_type, data))

            def run_agent():
                adapter = get_agent()
                agent = AIAgent(
                    model=adapter._model_id,
                    base_url=adapter._base_url,
                    api_key=adapter._api_key,
                )
                for name, func in adapter._tools:
                    agent.register_tool(name, func)
                return agent.query(request.message, on_event=on_event)

            task = asyncio.get_event_loop().run_in_executor(None, run_agent)

            while not task.done():
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    continue

            # Drain remaining events
            while not queue.empty():
                event_type, data = queue.get_nowait()
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

            answer = task.result()
            if answer:
                yield f"event: token\ndata: {json.dumps({'content': answer})}\n\n"

            yield "event: done\ndata: {}\n\n"

        except Exception:
            logger.exception("Error in stream event_generator")
            yield f"event: error\ndata: {json.dumps({'detail': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    """Return service health and whether the agent has been initialized."""
    return {"status": "healthy", "agent_initialized": get_agent is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
