"""
AI service for OpenAI Responses Agent: run the agent on request payload and return (generate, generate_stream).

Uses OpenAI client and Responses API. Both generate and generate_stream accept a context
whose get_json() returns the request payload (e.g. {"messages": [...]}).
"""
import asyncio
from typing import Generator

from openai_responses_agent_base.agent import get_agent_closure


def ai_stream_service(context, base_url=None, model_id=None):
    """Create a deployable AI service that runs the OpenAI Responses agent and returns (generate, generate_stream).

    Builds the agent closure once, then returns two callables: one for a single
    non-streaming response and one that yields one update (full answer) for compatibility
    with the interactive chat. Both accept a context object whose get_json() returns the
    request payload (e.g. {"messages": [...]}).

    Args:
        context: Object with get_json() used to read the request payload (not used at setup).
        base_url: LLM API base URL; uses BASE_URL env if omitted.
        model_id: LLM model id; uses MODEL_ID env if omitted.

    Returns:
        Tuple (generate, generate_stream). generate returns a dict with body/choices;
        generate_stream yields choice dicts with delta (one chunk with full content).
    """
    get_agent = get_agent_closure(base_url=base_url, model_id=model_id)

    def generate(context) -> dict:
        """Run the agent once on the context payload and return a single response dict (headers + body with choices)."""
        payload = context.get_json()
        messages = payload.get("messages", [])
        agent = get_agent()
        result = asyncio.run(agent.run(input=messages))
        # result["messages"] includes history + last assistant message
        last_msg = result["messages"][-1] if result["messages"] else {"role": "assistant", "content": ""}
        content = last_msg.get("content", "")
        return {
            "headers": {"Content-Type": "application/json"},
            "body": {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            },
        }

    def generate_stream(context) -> Generator[dict, None, None]:
        """Yield one choice delta with the full assistant answer (no true streaming; same format as LangGraph)."""
        payload = context.get_json()
        messages = payload.get("messages", [])
        agent = get_agent()
        result = asyncio.run(agent.run(input=messages))
        last_msg = result["messages"][-1] if result["messages"] else {"role": "assistant", "content": ""}
        content = last_msg.get("content", "")
        yield {
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ]
        }

    return generate, generate_stream
