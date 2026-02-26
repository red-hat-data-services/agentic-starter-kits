import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from pydantic import BaseModel
from langgraph.checkpoint.postgres import PostgresSaver

from langgraph_react_with_database_memory.agent import get_graph_closure
from langgraph_react_with_database_memory.utils import get_env_var, get_database_uri


# Request/Response models
class ChatRequest(BaseModel):
    """Incoming chat request body for the /chat endpoint."""

    messages: list[dict]
    thread_id: str | None = None


class ChatResponse(BaseModel):
    """Structured chat response with message history."""

    messages: list[dict]
    finish_reason: str


# Global variables
agent_graph_closure = None
DB_URI = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the ReAct agent graph on startup and clear it on shutdown.

    Reads environment variables, builds the graph closure,
    and sets up database connection.
    """
    global agent_graph_closure, DB_URI

    # Get environment variables
    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")

    # Ensure base_url ends with /v1 if provided
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    # Get database URI
    DB_URI = get_database_uri()

    # Setup database schema
    with PostgresSaver.from_conn_string(DB_URI) as saver:
        saver.setup()

    # Get graph closure
    agent_graph_closure = get_graph_closure(model_id=model_id, base_url=base_url)

    yield

    # Cleanup on shutdown
    agent_graph_closure = None
    DB_URI = None


# Create FastAPI app
app = FastAPI(
    title="LangGraph React Agent with Database Memory API",
    description="FastAPI service for LangGraph React Agent with PostgreSQL persistence",
    lifespan=lifespan,
)


def convert_dict_to_message(msg_dict: dict):
    """Convert message dict to LangChain message object."""
    role = msg_dict.get("role")
    content = msg_dict.get("content", "")

    if role == "system":
        return SystemMessage(content=content)
    elif role == "assistant":
        return AIMessage(content=content)
    else:  # user
        return HumanMessage(content=content)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat endpoint that accepts messages and returns the agent's response.
    Supports thread_id for conversation persistence.

    Args:
        request: ChatRequest containing messages list and optional thread_id

    Returns:
        JSON response with full conversation history including tool calls
    """
    global agent_graph_closure, DB_URI

    if agent_graph_closure is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        # Convert messages from dict to LangChain message objects
        messages = [convert_dict_to_message(msg) for msg in request.messages]

        # Extract system prompt if present
        system_prompt = None
        if messages and isinstance(messages[0], SystemMessage):
            system_prompt = messages[0].content
            messages = messages[1:]  # Remove system message from input

        # Get agent graph with database persistence
        with PostgresSaver.from_conn_string(DB_URI) as saver:
            if system_prompt:
                agent = agent_graph_closure(saver, request.thread_id, system_prompt)
            else:
                agent = agent_graph_closure(saver, request.thread_id)

            # Invoke agent with optional thread configuration
            if request.thread_id:
                config = {"configurable": {"thread_id": request.thread_id}}
                result = await agent.ainvoke(
                    {"messages": messages}, config=config
                )
            else:
                result = await agent.ainvoke({"messages": messages})

        # Format response messages
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

        return ChatResponse(messages=response_messages, finish_reason="stop")

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


@app.get("/health")
async def health():
    """Return service health and whether the agent graph has been initialized."""
    return {
        "status": "healthy",
        "agent_initialized": agent_graph_closure is not None,
        "database_connected": DB_URI is not None,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
