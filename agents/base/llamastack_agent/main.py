import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from llamastack_agent_base.agent import get_agent_closure
from llamastack_agent_base.utils import get_env_var
from pydantic import BaseModel


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
    """Initialize the LlamaStack agent closure on startup and clear it on shutdown.

    Reads BASE_URL and MODEL_ID from the environment and sets the global get_agent
    for the /chat endpoint. Uses only LlamaStack API (no LlamaIndex).
    """
    global get_agent

    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")

    # LlamaStack base_url is typically full (e.g. http://localhost:8321); no /v1 suffix required
    get_agent = get_agent_closure(base_url=base_url, model_id=model_id)

    yield

    get_agent = None


app = FastAPI(
    title="LlamaStack Agent API",
    description="FastAPI service for LlamaStack Agent (LlamaStack API only, no LlamaIndex)",
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


@app.get("/health")
async def health():
    """Return service health and whether the agent has been initialized."""
    return {"status": "healthy", "agent_initialized": get_agent is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
