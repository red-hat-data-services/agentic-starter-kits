from typing import Generator

from human_in_the_loop.agent import get_graph_closure
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command


def ai_stream_service(context, base_url=None, model_id=None):
    """Create a deployable AI service with HITL support that returns (generate, generate_stream).

    Builds the agent graph once with a MemorySaver checkpointer for HITL interrupt
    support, then returns two callables for non-streaming and streaming responses.

    Args:
        context: Object with get_json() used to read the request payload.
        base_url: LLM API base URL; uses BASE_URL env if omitted.
        model_id: LLM model id; uses MODEL_ID env if omitted.

    Returns:
        Tuple (generate, generate_stream).
    """
    graph_closure = get_graph_closure(model_id=model_id, base_url=base_url)
    checkpointer = MemorySaver()
    agent = graph_closure(checkpointer)

    def get_formatted_message(resp: BaseMessage) -> dict | None:
        """Turn a LangChain message into a display dict (role + content) for the client."""
        if isinstance(resp, ToolMessage):
            return {"role": "tool", "content": f"\n🔧 Tool Output:\n {resp.content}"}

        if hasattr(resp, "tool_calls") and resp.tool_calls:
            tc = resp.tool_calls[0]
            return {
                "role": "assistant",
                "content": f"🤔 I am calling tool '{tc['name']}' with args: {tc['args']}",
            }

        if resp.content:
            return {"role": "assistant", "content": resp.content}

        return None

    def convert_dict_to_message(_dict: dict) -> BaseMessage:
        """Convert a role/content dict from the client into a LangChain message."""
        role = _dict.get("role")
        content = _dict.get("content", "")
        if role == "assistant":
            return AIMessage(content=content)
        elif role == "system":
            return SystemMessage(content=content)
        return HumanMessage(content=content)

    def generate(context) -> dict:
        """Run the agent once on the context payload and return a single response dict."""
        payload = context.get_json()
        messages = [convert_dict_to_message(m) for m in payload.get("messages", [])]
        thread_id = payload.get("thread_id", "default")
        approval = payload.get("approval")
        config = {"configurable": {"thread_id": thread_id}}

        try:
            if approval:
                if approval.lower() in ("yes", "y", "approve"):
                    resume_value = {"decisions": [{"type": "approve"}]}
                else:
                    resume_value = {
                        "decisions": [
                            {
                                "type": "reject",
                                "message": "User rejected the tool call.",
                            }
                        ]
                    }
                result = agent.invoke(
                    Command(resume=resume_value), config=config, version="v2"
                )
            else:
                result = agent.invoke(
                    {"messages": messages}, config=config, version="v2"
                )

            if result.interrupts:
                interrupt_value = result.interrupts[0].value
                return {
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": str(interrupt_value),
                                },
                                "finish_reason": "pending_approval",
                            }
                        ],
                        "thread_id": thread_id,
                    },
                }

            all_messages = result.value.get("messages", [])
            final_msg = all_messages[-1] if all_messages else None

            return {
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": final_msg.content if final_msg else "",
                            },
                        }
                    ],
                    "thread_id": thread_id,
                },
            }
        except Exception:
            raise

    def generate_stream(context) -> Generator[dict, None, None]:
        """Stream agent updates (tool calls and final answer) as choice deltas."""
        payload = context.get_json()
        messages = [convert_dict_to_message(m) for m in payload.get("messages", [])]
        thread_id = payload.get("thread_id", "default")
        approval = payload.get("approval")
        config = {"configurable": {"thread_id": thread_id}}

        try:
            if approval:
                if approval.lower() in ("yes", "y", "approve"):
                    resume_value = {"decisions": [{"type": "approve"}]}
                else:
                    resume_value = {
                        "decisions": [
                            {
                                "type": "reject",
                                "message": "User rejected the tool call.",
                            }
                        ]
                    }
                input_data = Command(resume=resume_value)
            else:
                input_data = {"messages": messages}

            response_stream = agent.stream(
                input_data, config=config, stream_mode="updates"
            )

            for update in response_stream:
                if "__interrupt__" in update:
                    interrupt_info = update["__interrupt__"]
                    interrupt_value = interrupt_info[0].value if interrupt_info else {}
                    yield {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "content": str(interrupt_value),
                                },
                                "finish_reason": "pending_approval",
                            }
                        ],
                        "thread_id": thread_id,
                    }
                    continue

                for node_name, node_data in update.items():
                    if not isinstance(node_data, dict) or "messages" not in node_data:
                        continue

                    msgs = node_data["messages"]
                    if not isinstance(msgs, list):
                        msgs = [msgs]

                    for msg_obj in msgs:
                        message = get_formatted_message(msg_obj)
                        if message:
                            yield {
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": message,
                                        "finish_reason": None,
                                    }
                                ]
                            }

        except Exception:
            raise

    return generate, generate_stream
