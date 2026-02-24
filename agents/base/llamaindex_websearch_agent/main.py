import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llama_index_workflow_agent_base.agent import get_workflow_closure
from llama_index_workflow_agent_base.utils import get_env_var


# Request/Response models
class ChatRequest(BaseModel):
    """Incoming chat request body for the /chat endpoint."""

    message: str


class ChatResponse(BaseModel):
    """Structured chat response (answer and optional steps)."""

    answer: str
    steps: list[str]


# Global variable for workflow closure (get_agent callable)
get_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the LlamaIndex workflow closure on startup and clear it on shutdown.

    Reads BASE_URL and MODEL_ID from the environment, builds the workflow via
    get_workflow_closure, and sets the global get_agent for the /chat endpoint.
    """
    global get_agent

    # Get environment variables
    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")

    # Ensure base_url ends with /v1 if provided
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    # Get workflow closure (returns a callable that returns an agent)
    get_agent = get_workflow_closure(model_id=model_id, base_url=base_url)

    yield

    # Cleanup on shutdown (if needed)
    get_agent = None


# Create FastAPI app
app = FastAPI(
    title="LlamaIndex Websearch Agent API",
    description="FastAPI service for LlamaIndex Websearch Agent",
    lifespan=lifespan,
)


def _get_message_content(msg) -> str:
    """Extract text content from a LlamaIndex ChatMessage."""
    if hasattr(msg, "blocks") and msg.blocks:
        # Find the first block with text content (skip ToolCallBlock)
        for block in msg.blocks:
            if hasattr(block, "text"):
                return block.text or ""
        return ""
    if hasattr(msg, "content"):
        if isinstance(msg.content, str):
            return msg.content
        if isinstance(msg.content, list) and msg.content:
            first = msg.content[0]
            if isinstance(first, dict) and "text" in first:
                return first["text"] or ""
    return ""


def _message_to_response_dict(msg):
    """Map a LlamaIndex ChatMessage to the same format as LangGraph (role, content, tool_calls, etc.)."""
    role = getattr(msg, "role", "user")
    content = _get_message_content(msg)

    if role == "user":
        return {"role": "user", "content": content}

    if role == "assistant":
        msg_data = {"role": "assistant", "content": content or ""}
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls and getattr(msg, "additional_kwargs", None):
            tool_calls = msg.additional_kwargs.get("tool_calls")
        if tool_calls:
            if hasattr(tool_calls[0], "tool_id"):  # ToolSelection-like
                msg_data["tool_calls"] = [
                    {
                        "id": tc.tool_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.tool_kwargs),
                        },
                    }
                    for tc in tool_calls
                ]
            elif hasattr(tool_calls[0], "id") and hasattr(tool_calls[0], "function"):
                # ChatCompletionMessageFunctionToolCall object
                msg_data["tool_calls"] = []
                for tc in tool_calls:
                    fn = tc.function
                    args = fn.arguments if hasattr(fn, "arguments") else ""
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    msg_data["tool_calls"].append(
                        {
                            "id": tc.id,
                            "type": getattr(tc, "type", "function"),
                            "function": {
                                "name": fn.name if hasattr(fn, "name") else "",
                                "arguments": args,
                            },
                        }
                    )
            else:  # dict format (e.g. from additional_kwargs)
                msg_data["tool_calls"] = []
                for tc in tool_calls:
                    fn = tc.get("function", {}) or {}
                    args = fn.get("arguments", "")
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    msg_data["tool_calls"].append(
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": fn.get("name", ""), "arguments": args},
                        }
                    )
        return msg_data

    if role == "tool":
        additional = getattr(msg, "additional_kwargs", {}) or {}
        return {
            "role": "tool",
            "tool_call_id": additional.get("tool_call_id", ""),
            "name": additional.get("name", ""),
            "content": content,
        }

    return None  # skip system or unknown


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint that accepts a message and returns the agent's response.

    Args:
        request: ChatRequest containing the user message

    Returns:
        JSON response with full conversation history including tool calls
    """
    global get_agent

    if get_agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        agent = get_agent()
        messages = [{"role": "user", "content": request.message}]

        result = await agent.run(input=messages)

        response_messages = []

        if result and "messages" in result and len(result["messages"]) > 0:
            for message in result["messages"]:
                if getattr(message, "role", None) == "system":
                    continue
                item = _message_to_response_dict(message)
                if item is not None:
                    response_messages.append(item)

        return {"messages": response_messages, "finish_reason": "stop"}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


@app.get("/health")
async def health():
    """Return service health and whether the workflow closure has been initialized."""
    return {"status": "healthy", "agent_initialized": get_agent is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
