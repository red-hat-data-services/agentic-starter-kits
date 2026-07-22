from os import getenv
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from guardrailed_agent.tools import check_account_balance


def get_graph_closure(
    model_id: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Build and return a LangGraph ReAct agent for banking customer service.

    Creates a ChatOpenAI client, wires check_account_balance tool,
    and uses create_agent to produce a graph that runs the ReAct loop.

    Args:
        model_id: LLM model identifier. Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted.

    Returns:
        A LangGraph agent (CompiledGraph) that accepts {"messages": [...]} and returns updated state.
    """

    if not api_key:
        api_key = getenv("API_KEY")
    if not base_url:
        base_url = getenv("BASE_URL")
    if not model_id:
        model_id = getenv("MODEL_ID")

    if not base_url:
        raise ValueError(
            "BASE_URL is required. Set it via argument or BASE_URL env var."
        )
    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])

    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    tools = [check_account_balance]

    chat = ChatOpenAI(
        model=model_id,
        temperature=0.01,
        api_key=api_key,
        base_url=base_url,
    )

    system_prompt = """You are a customer service assistant for a retail bank.
        You help customers with account inquiries, billing, payments, and general
        banking questions. When you receive a result from a tool, use that
        information to provide a FINAL answer to the customer immediately.
        Do NOT call tools repeatedly for the same question.
        Always be professional and helpful."""
    agent = create_agent(model=chat, tools=tools, system_prompt=system_prompt)

    return agent
