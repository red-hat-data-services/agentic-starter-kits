import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel

from langgraph_react_agent_base.agent import get_graph_closure
from langgraph_react_agent_base.utils import get_env_var


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
    """Initialize the ReAct agent graph on startup and clear it on shutdown.

    Reads BASE_URL and MODEL_ID from the environment, builds the graph via
    get_graph_closure, and sets the global agent_graph for the /chat endpoint.
    """
    global agent_graph

    # Get environment variables
    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")

    # Ensure base_url ends with /v1 if provided
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    # Get graph closure and create agent graph
    agent_graph = get_graph_closure(model_id=model_id, base_url=base_url)

    yield

    # Cleanup on shutdown (if needed)
    agent_graph = None


# Create FastAPI app
app = FastAPI(
    title="LangGraph React Agent API",
    description="FastAPI service for LangGraph React Agent",
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
            {"messages": messages}, config={"recursion_limit": 10}
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


@app.get("/health")
async def health():
    """Return service health and whether the agent graph has been initialized."""
    return {"status": "healthy", "agent_initialized": agent_graph is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
