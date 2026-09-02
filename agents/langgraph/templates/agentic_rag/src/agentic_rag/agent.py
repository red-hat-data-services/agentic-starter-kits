from os import getenv
from typing import Callable

from langchain.agents import create_agent
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from .tools import retriever_tool


def get_graph_closure(
    model_id: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Callable:
    """Build and return a LangGraph ReAct agent with the configured LLM and retrieval tool.

    Creates a ChatOpenAI client, wires a retriever tool based on vector store configuration,
    and uses create_react_agent to produce a ReAct workflow.

    Args:
        model_id: LLM model identifier (e.g. for OpenAI-compatible API). Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted; required for non-local base_url.

    Returns:
        A function that creates a CompiledGraph agent accepting {"messages": [...]} and returns updated state.
    """

    # Get environment variables if not provided
    if not api_key:
        api_key = getenv("API_KEY")
    if not base_url:
        base_url = getenv("BASE_URL")
    if not model_id:
        model_id = getenv("MODEL_ID")

    # Check if using local deployment
    if not base_url:
        raise ValueError(
            "BASE_URL is required. Set it via argument or BASE_URL env var."
        )
    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])

    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    # Initialize ChatOpenAI
    #  model_kwargs with tool_choice to force tool usage for Hermes-based models
    chat = ChatOpenAI(
        model=model_id,
        temperature=0.0,  # Lower temperature for more consistent reasoning
        api_key=api_key or "not-needed-for-local-development",
        base_url=base_url,
        model_kwargs={"tool_choice": "auto"},  # Enable tool choice for Hermes parser
    )

    TOOLS = [retriever_tool]

    # Define system prompt for ReAct agent
    # CRITICAL: Use explicit instruction for Hermes tool calling parser
    default_system_prompt = (
        "You are a helpful AI assistant with access to a retriever tool for searching a knowledge base.\n\n"
        "CRITICAL INSTRUCTION: When a user asks ANY question, you MUST respond by calling the 'retriever' tool FIRST. "
        "Do NOT attempt to answer from your own knowledge until AFTER you have called the retriever tool and seen its results.\n\n"
        "Process:\n"
        "1. User asks a question → immediately call retriever tool with relevant search query\n"
        "2. Receive retriever results → use them to formulate your answer\n"
        "3. If no relevant information found → then use general knowledge\n"
        "4. Always cite sources when available\n\n"
        "Example:\n"
        "User: 'What are appropriate chunk sizes?'\n"
        "You: [MUST call retriever tool with query='chunk sizes' or 'appropriate chunk sizes']"
    )

    def get_graph(
        instruction_prompt: SystemMessage | None = None,
    ) -> CompiledStateGraph:
        """Create and compile the ReAct agent graph.

        Args:
            instruction_prompt: Optional custom system message to override default

        Returns:
            CompiledGraph: The compiled LangGraph ReAct workflow
        """
        # Combine default and custom prompts
        system_message_text = default_system_prompt
        if instruction_prompt is not None:
            system_message_text = default_system_prompt + "\n\n" + instruction_prompt.content

        # Create agent using LangChain's create_agent
        graph = create_agent(
            model=chat,
            tools=TOOLS,
            system_prompt=system_message_text,
        )

        return graph

    return get_graph
