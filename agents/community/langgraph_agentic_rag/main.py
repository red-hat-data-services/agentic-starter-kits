import json
import logging
from contextlib import asynccontextmanager
from os import getenv

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from langgraph_agentic_rag.agent import get_graph_closure


# Request/Response models
class ChatRequest(BaseModel):
    """Incoming chat request body for the /chat endpoint."""

    message: str


class ChatResponse(BaseModel):
    """Structured chat response (answer and optional steps)."""

    answer: str
    steps: list[str]


# Global variable for agent graph
agent_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the RAG agent graph on startup and clear it on shutdown.

    Reads BASE_URL, MODEL_ID, and RAG-specific configuration from the environment,
    builds the graph via get_graph_closure, and sets the global agent_graph for the /chat endpoint.
    """
    global agent_graph

    # Get environment variables
    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")

    # Ensure base_url ends with /v1 if provided
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    # Get graph closure and create agent graph
    graph_closure = get_graph_closure(
        model_id=model_id,
        base_url=base_url,
    )
    agent_graph = graph_closure()

    yield

    # Cleanup on shutdown (if needed)
    agent_graph = None


# Create FastAPI app
app = FastAPI(
    title="LangGraph Agentic RAG API",
    description="FastAPI service for LangGraph Agentic RAG Agent",
    lifespan=lifespan,
)


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint that accepts a message and returns the agent's response.

    Args:
        request: ChatRequest containing the user message

    Returns:
        JSON response with full conversation history including tool calls
    """
    global agent_graph

    if agent_graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        messages = [HumanMessage(content=request.message)]

        # Use invoke to get the agent's response
        result = await agent_graph.ainvoke(
            {"messages": messages}, config={"recursion_limit": 15}
        )

        response_messages = []

        if "messages" in result and len(result["messages"]) > 0:
            for message in result["messages"]:
                # 1. User message (HumanMessage)
                if isinstance(message, HumanMessage):
                    response_messages.append(
                        {
                            "role": "user",
                            "content": message.content,
                        }
                    )

                # 2. AI message (AIMessage)
                elif isinstance(message, AIMessage):
                    msg_data = {
                        "role": "assistant",
                        "content": message.content or "",
                    }
                    if message.tool_calls:
                        msg_data["tool_calls"] = [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["args"]),
                                },
                            }
                            for tc in message.tool_calls
                        ]
                    response_messages.append(msg_data)

                # 3. Tool response (ToolMessage)
                elif isinstance(message, ToolMessage):
                    response_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": message.tool_call_id,
                            "name": message.name,
                            "content": message.content,
                        }
                    )

        return {"messages": response_messages, "finish_reason": "stop"}

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
        - token: streamed text token from the LLM
        - tool_call: tool invocation by the agent
        - tool_result: result returned by a tool
        - done: signals the stream is complete

    Args:
        request: ChatRequest containing the user message
    """
    global agent_graph

    if agent_graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    async def event_generator():
        try:
            messages = [HumanMessage(content=request.message)]

            async for event in agent_graph.astream_events(
                {"messages": messages},
                config={"recursion_limit": 15},
                version="v2",
            ):
                kind = event["event"]

                # LLM streaming tokens
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        yield f"event: token\ndata: {json.dumps({'content': chunk.content})}\n\n"

                # Complete tool call (after LLM finishes generating the call)
                elif kind == "on_chat_model_end":
                    message = event["data"]["output"]
                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tc in message.tool_calls:
                            yield f"event: tool_call\ndata: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"

                # Tool execution results
                elif kind == "on_tool_end":
                    output = event["data"].get("output", "")
                    if hasattr(output, "content"):
                        output = output.content
                    yield f"event: tool_result\ndata: {json.dumps({'name': event.get('name', ''), 'output': str(output)})}\n\n"

            yield "event: done\ndata: {}\n\n"

        except Exception as e:
            logger.exception("Error in stream event_generator")
            yield f"event: error\ndata: {json.dumps({'detail': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    """Return service health and whether the agent graph has been initialized."""
    return {"status": "healthy", "agent_initialized": agent_graph is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
