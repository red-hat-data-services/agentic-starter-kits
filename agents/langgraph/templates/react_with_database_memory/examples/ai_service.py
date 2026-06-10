from typing import Generator

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.postgres import PostgresSaver
from react_with_database_memory.agent import get_graph_closure
from react_with_database_memory.utils import get_database_uri


def ai_stream_service(
    context, base_url=None, model_id=None, postgres_db_connection_id=None
):
    agent_closure = get_graph_closure(
        model_id=model_id,
        base_url=base_url,
    )

    DB_URI = get_database_uri()

    with PostgresSaver.from_conn_string(DB_URI) as saver:
        saver.setup()

    def get_formatted_message(
        resp: BaseMessage, is_assistant: bool = False
    ) -> dict | None:
        role = resp.type

        if resp.content:
            if role in {"AIMessageChunk", "ai"}:
                return {"role": "assistant", "content": resp.content}
            elif role == "tool":
                if is_assistant:
                    return {
                        "role": "assistant",
                        "step_details": {
                            "type": "tool_response",
                            "id": resp.id,
                            "tool_call_id": resp.tool_call_id,
                            "name": resp.name,
                            "content": resp.content,
                        },
                    }
                else:
                    return {
                        "role": role,
                        "id": resp.id,
                        "tool_call_id": resp.tool_call_id,
                        "name": resp.name,
                        "content": resp.content,
                    }
        elif role == "ai":  # this implies resp.additional_kwargs
            if additional_kw := resp.additional_kwargs:
                tool_call = additional_kw["tool_calls"][0]
                if is_assistant:
                    return {
                        "role": "assistant",
                        "step_details": {
                            "type": "tool_calls",
                            "tool_calls": [
                                {
                                    "id": tool_call["id"],
                                    "name": tool_call["function"]["name"],
                                    "args": tool_call["function"]["arguments"],
                                }
                            ],
                        },
                    }
                else:
                    return {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tool_call["id"],
                                "type": "function",
                                "function": {
                                    "name": tool_call["function"]["name"],
                                    "arguments": tool_call["function"]["arguments"],
                                },
                            }
                        ],
                    }

    def convert_dict_to_message(_dict: dict) -> BaseMessage:
        """Convert user message in dict to langchain_core.messages.BaseMessage"""

        role = _dict.get("role")
        content = _dict.get("content", "")
        if role == "assistant":
            return AIMessage(content=content)
        elif role == "system":
            return SystemMessage(content=content)
        return HumanMessage(content=content)

    def generate(context) -> dict:
        payload = context.get_json()
        raw_messages = payload.get("messages", [])
        thread_id = payload.get("thread_id")
        messages = [convert_dict_to_message(_dict) for _dict in raw_messages]

        with PostgresSaver.from_conn_string(DB_URI) as saver:
            if messages and messages[0].type == "system":
                agent = agent_closure(saver, thread_id, messages[0].content)
                del messages[0]
            else:
                agent = agent_closure(saver, thread_id)

            if thread_id:
                config = {"configurable": {"thread_id": thread_id}}
                generated_response = agent.invoke({"messages": messages}, config)
            else:
                generated_response = agent.invoke({"messages": messages})

            choices = []
            execute_response = {
                "headers": {"Content-Type": "application/json"},
                "body": {"choices": choices},
            }

            choices.append(
                {
                    "index": 0,
                    "message": get_formatted_message(
                        generated_response["messages"][-1]
                    ),
                }
            )

            return execute_response

    def generate_stream(context) -> Generator[dict, ..., ...]:
        headers = context.get_headers()
        is_assistant = headers.get("X-Ai-Interface") == "assistant"

        payload = context.get_json()
        raw_messages = payload.get("messages", [])
        thread_id = payload.get("thread_id")
        messages = [convert_dict_to_message(_dict) for _dict in raw_messages]

        with PostgresSaver.from_conn_string(DB_URI) as saver:
            if messages and messages[0].type == "system":
                agent = agent_closure(saver, thread_id, messages[0].content)
                del messages[0]
            else:
                agent = agent_closure(saver, thread_id)

            if thread_id:
                config = {"configurable": {"thread_id": thread_id}}
                response_stream = agent.stream(
                    {"messages": messages}, config, stream_mode=["updates", "messages"]
                )
            else:
                response_stream = agent.stream(
                    {"messages": messages}, stream_mode=["updates", "messages"]
                )

            for chunk_type, data in response_stream:
                msg_obj = None

                if chunk_type == "messages":
                    msg_obj = data[0]
                    # Skip tool messages (internal)
                    if msg_obj.type == "tool":
                        continue
                    # Skip system messages
                    if msg_obj.type == "system":
                        continue
                elif chunk_type == "updates":
                    # create_agent uses node name "model" (not "agent")
                    if model_data := data.get("model"):
                        msg_obj = model_data["messages"][0]
                    elif tool_data := data.get("tools"):
                        msg_obj = tool_data["messages"][0]
                    else:
                        # Skip updates without messages (e.g., middleware)
                        continue
                else:
                    continue

                # Format and yield the message if valid
                if (
                    msg_obj
                    and (
                        message := get_formatted_message(
                            msg_obj, is_assistant=is_assistant
                        )
                    )
                    is not None
                ):
                    chunk_response = {
                        "choices": [
                            {
                                "index": 0,
                                "delta": message,
                                "finish_reason": msg_obj.response_metadata.get(
                                    "finish_reason"
                                ),
                            }
                        ]
                    }
                    yield chunk_response

    return generate, generate_stream
