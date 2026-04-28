import os
from os import getenv

import litellm
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner

from adk_agent import TOOLS

# Suppress LiteLLM's internal telemetry/logging worker timeout errors
litellm.suppress_debug_info = True
litellm.telemetry = False

APP_NAME = "adk_agent"


def get_agent(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> LlmAgent:
    """Build and return a Google ADK LlmAgent configured for LlamaStack via LiteLLM.

    Uses the LiteLlm model connector with the "openai/" provider prefix to route
    inference requests through LlamaStack's OpenAI-compatible API.

    Args:
        model_id: LLM model identifier. Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted.

    Returns:
        A configured LlmAgent instance.
    """
    if not api_key:
        api_key = getenv("API_KEY")
    if not base_url:
        base_url = getenv("BASE_URL")
    if not model_id:
        model_id = getenv("MODEL_ID")

    if not base_url:
        raise ValueError("BASE_URL is required. Set it via argument or BASE_URL env var.")

    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])
    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    # Configure LiteLLM's OpenAI provider environment for LlamaStack
    os.environ["OPENAI_API_BASE"] = base_url
    os.environ["OPENAI_API_KEY"] = api_key or "not-needed-for-local-development"

    model = LiteLlm(model=f"openai/{model_id}")

    agent = LlmAgent(
        name=APP_NAME,
        model=model,
        description="Agent that answers questions using web search.",
        instruction=(
            "You are a helpful assistant. When you receive a result from a tool, "
            "use that information to provide a FINAL answer to the user immediately. "
            "Do NOT call tools repeatedly for the same question."
        ),
        tools=TOOLS,
    )

    return agent


def get_runner(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> InMemoryRunner:
    """Build an InMemoryRunner wrapping the ADK agent.

    Args:
        model_id: LLM model identifier.
        base_url: Base URL for the LLM API.
        api_key: API key for the LLM.

    Returns:
        An InMemoryRunner ready to create sessions and run the agent.
    """
    agent = get_agent(model_id=model_id, base_url=base_url, api_key=api_key)
    return InMemoryRunner(agent=agent, app_name=APP_NAME)
