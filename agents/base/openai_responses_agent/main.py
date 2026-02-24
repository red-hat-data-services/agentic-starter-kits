import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from openai_responses_agent_base.agent import get_agent_closure
from openai_responses_agent_base.utils import get_env_var
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
    """Initialize the agent closure on startup and clear it on shutdown.

    Reads BASE_URL and MODEL_ID from the environment and sets the global get_agent
    for the /chat endpoint. Uses OpenAI client and Responses API (no agentic framework).
    """
    global get_agent

    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")

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


@app.get("/health")
async def health():
    """Return service health and whether the agent has been initialized."""
    return {"status": "healthy", "agent_initialized": get_agent is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
