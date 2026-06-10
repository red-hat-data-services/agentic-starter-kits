from os import getenv
from typing import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from human_in_the_loop import TOOLS


def get_graph_closure(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> Callable:
    """Build and return a closure that creates HITL agent graphs.

    Uses create_agent with HumanInTheLoopMiddleware to pause execution before
    sensitive tool calls (e.g. create_file), requiring human approval via
    Command(resume=...) to proceed.

    Args:
        model_id: LLM model identifier. Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted.

    Returns:
        A closure that accepts a checkpointer and returns a compiled agent graph.
    """

    if not api_key:
        api_key = getenv("API_KEY")
    if not base_url:
        base_url = getenv("BASE_URL")
    if not model_id:
        model_id = getenv("MODEL_ID")

    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])
    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    chat = ChatOpenAI(
        model=model_id,
        temperature=0.01,
        api_key=api_key,
        base_url=base_url,
    )

    system_prompt = (
        "You are a helpful AI assistant. You have access to ONE tool:\n"
        "- create_file(filename, content): Create a file with given name and content.\n\n"
        "IMPORTANT RULES:\n"
        "- ONLY use the create_file tool when the user EXPLICITLY asks you to create, write, "
        "or generate a file. Look for keywords like 'create a file', 'write a file', 'make a file', "
        "'generate a file'.\n"
        "- For ALL other requests (greetings, questions, conversations), respond with plain text. "
        "Do NOT call create_file.\n"
        "- When you do use create_file, provide the actual file content directly as a string, "
        "not as JSON schema or metadata.\n"
        "- After receiving a tool result, provide a FINAL answer immediately. "
        "Do NOT call tools repeatedly for the same question."
    )

    # HumanInTheLoopMiddleware pauses the graph before executing create_file
    # and waits for human approval via Command(resume=...)
    hitl_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "create_file": True,
        },
    )

    def get_graph(checkpointer: BaseCheckpointSaver = None) -> CompiledStateGraph:
        """Create a compiled HITL agent with the given checkpointer.

        Args:
            checkpointer: A LangGraph checkpoint saver for state persistence.
                          Required for HITL to work. Defaults to MemorySaver.

        Returns:
            A compiled agent graph with human-in-the-loop interrupt capability.
        """
        if checkpointer is None:
            checkpointer = MemorySaver()

        agent = create_agent(
            model=chat,
            tools=TOOLS,
            system_prompt=system_prompt,
            middleware=[hitl_middleware],
            checkpointer=checkpointer,
        )

        return agent

    return get_graph
