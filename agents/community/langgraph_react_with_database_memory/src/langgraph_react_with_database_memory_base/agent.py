from typing import Callable

from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from langchain.agents import create_agent
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph_react_with_database_memory_base.utils import get_env_var
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse


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
        api_key = get_env_var("API_KEY")
    if not base_url:
        base_url = get_env_var("BASE_URL")
    if not model_id:
        model_id = get_env_var("MODEL_ID")

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
        memory: PostgresSaver, thread_id=None, system_prompt=default_system_prompt
    ) -> CompiledStateGraph:
        """Get compiled graph with overwritten system prompt, if provided"""

        @wrap_model_call
        def messages_modifier(
            request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
        ) -> ModelResponse:
            """Reduces number of agent's input messages right before LLM execution.

            Keeps only the most recent max_messages_in_context conversation messages
            (FIFO). The system prompt is handled separately by create_agent via
            request.system_message and is NOT part of request.messages.
            """
            messages = request.messages

            if len(messages) > max_messages_in_context:
                messages = messages[-max_messages_in_context:]

            return handler(request.override(messages=messages))

        if thread_id:
            return create_agent(
                chat,
                tools=[],
                checkpointer=memory,
                system_prompt=system_prompt,
                middleware=[messages_modifier],  # Properly inject the middleware
            )
        else:
            return create_agent(chat, tools=[], system_prompt=system_prompt)

    return get_graph
