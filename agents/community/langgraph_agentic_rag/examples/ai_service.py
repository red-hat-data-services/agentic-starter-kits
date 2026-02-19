from typing import Generator
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, BaseMessage, ToolMessage
from langgraph_agentic_rag.agent import get_graph_closure

def ai_stream_service(
        context,
        base_url=None,
        model_id=None,
):
    """Create a deployable AI service that runs the RAG agent and returns (generate, generate_stream).

    Builds the agent graph once, then returns two callables: one for a single
    non-streaming response and one that streams agent updates (retrieval and
    final answer). Both accept a context object whose get_json() returns the
    request payload (e.g. {"messages": [...]}).

    Args:
        context: Object with get_json() used to read the request payload (not used at setup).
        base_url: LLM API base URL; uses BASE_URL env if omitted.
        model_id: LLM model id; uses MODEL_ID env if omitted.
    Returns:
        Tuple (generate, generate_stream). Each takes context and returns a response
        (dict with body/choices for generate, generator of choice dicts for generate_stream).
    """
    agent_closure = get_graph_closure(
        model_id=model_id,
        base_url=base_url,
    )
    agent = agent_closure()

    def get_formatted_message(resp: BaseMessage) -> dict | None:
        """Turn a LangChain message into a display dict (role + content) for the client."""
        if isinstance(resp, ToolMessage):
            return {
                "role": "tool",
                "content": f"\n📚 Retrieved Documents:\n{resp.content}"
            }

        if hasattr(resp, "tool_calls") and resp.tool_calls:
            tc = resp.tool_calls[0]
            return {
                "role": "assistant",
                "content": f"🔍 Searching knowledge base with query: '{tc['args'].get('query', 'N/A')}'"
            }

        if resp.content:
            return {"role": "assistant", "content": resp.content}

        return None

    def convert_dict_to_message(_dict: dict) -> BaseMessage:
        """Convert a role/content dict from the client into a LangChain HumanMessage/AIMessage/SystemMessage."""
        role = _dict.get("role")
        content = _dict.get("content", "")
        if role == "assistant":
            return AIMessage(content=content)
        elif role == "system":
            return SystemMessage(content=content)
        return HumanMessage(content=content)

    def generate(context) -> dict:
        """Run the agent once on the context payload and return a single response dict (headers + body with choices)."""
        payload = context.get_json()
        messages = [convert_dict_to_message(m) for m in payload.get("messages", [])]
        result = agent.invoke({"messages": messages})
        final_msg = result["messages"][-1]

        return {
            "headers": {"Content-Type": "application/json"},
            "body": {
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": final_msg.content}
                }]
            }
        }

    def generate_stream(context) -> Generator[dict, None, None]:
        """Stream agent updates (retrieval and final answer) as choice deltas from the context payload."""
        payload = context.get_json()
        messages = [convert_dict_to_message(m) for m in payload.get("messages", [])]

        response_stream = agent.stream(
            {"messages": messages},
            stream_mode="updates"
        )

        for update in response_stream:
            node_name = list(update.keys())[0]
            data = update[node_name]

            if "messages" in data:
                # Handle cases where multiple messages might be in one update
                msgs = data["messages"]
                if not isinstance(msgs, list):
                    msgs = [msgs]

                for msg_obj in msgs:
                    message = get_formatted_message(msg_obj)

                    # Only yield if it's a valid message for the user
                    if message:
                        yield {
                            "choices": [{
                                "index": 0,
                                "delta": message,
                                "finish_reason": None
                            }]
                        }

    return generate, generate_stream