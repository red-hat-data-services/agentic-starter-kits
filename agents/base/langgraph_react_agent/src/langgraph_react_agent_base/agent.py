from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from langgraph_react_agent_base.tools import dummy_web_search, dummy_math
from langgraph_react_agent_base.utils import get_env_var


def get_graph_closure(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> Any:
    """Build and return a LangGraph ReAct agent with the configured LLM and tools.

    Creates a ChatOpenAI client, wires dummy_web_search and dummy_math tools,
    and uses create_agent to produce a graph that runs the ReAct loop (reason,
    act with tools, observe, repeat until a final answer).

    Args:
        model_id: LLM model identifier (e.g. for OpenAI-compatible API). Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted; required for non-local base_url.

    Returns:
        A LangGraph agent (CompiledGraph) that accepts {"messages": [...]} and returns updated state.
    """

    if not api_key:
        api_key = get_env_var("API_KEY")
    if not base_url:
        base_url = get_env_var("BASE_URL")
    if not model_id:
        model_id = get_env_var("MODEL_ID")

    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])

    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    tools = [dummy_web_search, dummy_math]

    chat = ChatOpenAI(
        model=model_id,
        temperature=0.01,
        api_key=api_key,
        base_url=base_url,
    )

    system_prompt = """You are a helpful assistant. When you receive a result from a tool, 
        use that information to provide a FINAL answer to the user immediately. 
        Do NOT call tools repeatedly for the same question."""
    agent = create_agent(model=chat, tools=tools, system_prompt=system_prompt)

    return agent
