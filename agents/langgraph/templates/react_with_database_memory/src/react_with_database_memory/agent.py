from os import getenv
from typing import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from react_with_database_memory import TOOLS


class FIFOMessageTrimmer(AgentMiddleware):
    """Middleware that trims conversation messages to a fixed window (FIFO).

    Keeps only the most recent `max_messages` conversation messages before
    sending to the LLM. The system prompt is handled separately by create_agent
    and is NOT part of request.messages.

    Supports both sync (invoke/stream) and async (ainvoke/astream) execution.
    """

    def __init__(self, max_messages: int = 5):
        self.max_messages = max_messages

    @staticmethod
    def _drop_orphaned_tool_messages(messages):
        """Remove leading tool messages that lost their preceding ai tool_calls."""
        while messages and messages[0].type == "tool":
            messages = messages[1:]
        return messages

    def wrap_model_call(self, request, handler):
        messages = request.messages
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages :]
            messages = self._drop_orphaned_tool_messages(messages)
        return handler(request.override(messages=messages))

    async def awrap_model_call(self, request, handler):
        messages = request.messages
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages :]
            messages = self._drop_orphaned_tool_messages(messages)
        return await handler(request.override(messages=messages))


def get_graph_closure(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> Callable:
    """Graph generator closure with OpenAI-compatible LLM client.

    Args:
        model_id: LLM model identifier (e.g. for OpenAI-compatible API). Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted; required for non-local base_url.

    Returns:
        A function that creates compiled agent graphs with optional database persistence.
    """

    # Load environment variables if not provided
    if not api_key:
        api_key = getenv("API_KEY")
    if not base_url:
        base_url = getenv("BASE_URL")
    if not model_id:
        model_id = getenv("MODEL_ID")

    # Ensure base_url ends with /v1
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    # Validate API key for non-local environments
    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])
    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    # Initialize ChatOpenAI
    chat = ChatOpenAI(
        model=model_id,
        temperature=0.01,
        api_key=api_key,
        base_url=base_url,
    )

    # Define system prompt
    default_system_prompt = "You are a helpful AI assistant, please respond to the user's query to the best of your ability!"

    max_messages_in_context = 5

    def get_graph(
        memory: BaseCheckpointSaver, thread_id=None, system_prompt=default_system_prompt
    ) -> CompiledStateGraph:
        """Get compiled graph with overwritten system prompt, if provided"""

        fifo_middleware = FIFOMessageTrimmer(max_messages=max_messages_in_context)

        if thread_id:
            return create_agent(
                chat,
                tools=TOOLS,
                checkpointer=memory,
                system_prompt=system_prompt,
                middleware=[fifo_middleware],
            )
        else:
            return create_agent(chat, tools=TOOLS, system_prompt=system_prompt)

    return get_graph
