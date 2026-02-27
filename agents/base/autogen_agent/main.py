import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from autogen_core import CancellationToken
from autogen_agentchat.messages import TextMessage

from autogen_agent_base.agent import get_agent_chat
from autogen_agent_base.utils import get_env_var


# Request/Response models
class ChatRequest(BaseModel):
    """Incoming chat request body for the /chat endpoint."""

    message: str


class ChatResponse(BaseModel):
    """Structured chat response (answer and optional steps)."""

    answer: str
    steps: list[str]


# Global: get_agent factory (creates a new agent per call)
get_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the AutoGen agent factory on startup."""
    global get_agent

    # Get environment variables
    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")
    api_key = get_env_var("API_KEY")

    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    get_agent = get_agent_chat(model_id=model_id, base_url=base_url, api_key=api_key)

    yield

    get_agent = None


app = FastAPI(
    title="AutoGen Agent API",
    description="FastAPI service for AutoGen AssistantAgent with OpenAI",
    lifespan=lifespan,
)


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint: accepts a message and returns the agent's response.
    """
    global get_agent

    if get_agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        agent = get_agent()
        cancel_token = CancellationToken()
        result = await agent.run(
            task=request.message,
            cancellation_token=cancel_token,
        )

        response_messages = [{"role": "user", "content": request.message}]

        if result.messages:
            last = result.messages[-1]
            content = getattr(last, "content", None) or str(last)
            if isinstance(last, TextMessage):
                content = last.content or ""
            response_messages.append({"role": "assistant", "content": content})
        else:
            response_messages.append({"role": "assistant", "content": ""})

        return {"messages": response_messages, "finish_reason": "stop"}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing request: {str(e)}",
        )


@app.get("/health")
async def health():
    """Return service health and whether the agent factory has been initialized."""
    return {"status": "healthy", "agent_initialized": get_agent is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
