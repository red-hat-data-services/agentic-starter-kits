from typing import Callable

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent

from autogen_agent_base import TOOLS


def get_agent_chat(
    model_id: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Callable:
    """Workflow generator closure using OpenAI or OpenAI-compatible API."""

    model_client = OpenAIChatCompletionClient(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
    )

    default_system_prompt = "You are a helpful AI assistant, please respond to the user's query to the best of your ability!"

    def get_agent(system_prompt: str = default_system_prompt) -> AssistantAgent:
        """Get compiled workflow with overwritten system prompt, if provided"""
        return AssistantAgent(
            name="assistant",
            model_client=model_client,
            tools=TOOLS,
            system_message=system_prompt,
            model_client_stream=True,
            reflect_on_tool_use=True,
        )

    return get_agent
