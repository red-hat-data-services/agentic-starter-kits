from os import getenv
from typing import Callable

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ModelFamily
from autogen_ext.models.openai import OpenAIChatCompletionClient

from autogen_agent_base import TOOLS


def get_agent_chat(
    model_id: str,
    base_url: str | None = None,
    api_key: str | None = None,
    tools: list | None = None,
) -> Callable:
    """Workflow generator closure using OpenAI or OpenAI-compatible API.

    Args:
        model_id: LLM model identifier.
        base_url: Base URL for the API (e.g. OpenAI-compatible or Llama Stack).
        api_key: API key (optional for some endpoints).
        tools: Optional list of tools (e.g. MCP tool adapters). When None, uses TOOLS from this module.
    """
    model_client = OpenAIChatCompletionClient(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": False,
            "family": ModelFamily.UNKNOWN,
            "structured_output": True,
        },
    )
    effective_tools = tools if tools is not None else TOOLS

    default_system_prompt = "You are a helpful AI assistant, please respond to the user's query to the best of your ability!"

    def get_agent(system_prompt: str = default_system_prompt) -> AssistantAgent:
        """Get AssistantAgent with overwritten system prompt, if provided."""
        # Streaming is enabled by default for playground compatibility.
        # When MLFLOW_TRACKING_URI is set, streaming is disabled to ensure
        # complete traces (mlflow.autogen.autolog() doesn't support streaming).
        # MODEL_CLIENT_STREAM can always be set explicitly to override.
        explicit = getenv("MODEL_CLIENT_STREAM")
        if explicit is not None:
            stream = explicit.lower() == "true"
        else:
            stream = not bool(getenv("MLFLOW_TRACKING_URI"))

        return AssistantAgent(
            name="assistant",
            model_client=model_client,
            tools=effective_tools,
            system_message=system_prompt,
            model_client_stream=stream,
            reflect_on_tool_use=True,
        )

    return get_agent
