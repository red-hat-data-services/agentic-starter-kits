from typing import Generator
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

# Importing your specific method
from langgraph_react_with_database_memory_base.agent import get_graph_closure
from langgraph_react_with_database_memory_base.utils import get_database_uri


def ai_stream_service(
    context, base_url=None, model_id=None, postgres_db_connection_id=None
):
    # 1. Initialize the agent factory using your method
    # This prepares the logic for the model and the graph structure
    agent_closure = get_graph_closure(
        model_id=model_id,
        base_url=base_url,  # Mapping 'url' to 'base_url' per your requirement
    )

    DB_URI = get_database_uri()

    def get_formatted_message(
        resp: BaseMessage, is_assistant: bool = False
    ) -> dict | None:
        role = resp.type
        if resp.content:
            if role in {"AIMessageChunk", "ai"}:
                return {"role": "assistant", "content": resp.content}
            elif role == "tool":
                return {
                    "role": "assistant" if is_assistant else "tool",
                    "step_details" if is_assistant else "content": {
                        "type": "tool_response",
                        "id": resp.id,
                        "tool_call_id": resp.tool_call_id,
                        "name": resp.name,
                        "content": resp.content,
                    }
                    if is_assistant
                    else resp.content,
                }
        elif role == "ai" and "tool_calls" in resp.additional_kwargs:
            tool_call = resp.additional_kwargs["tool_calls"][0]
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
        return None

    def convert_dict_to_message(_dict: dict) -> BaseMessage:
        if _dict["role"] == "assistant":
            return AIMessage(content=_dict["content"])
        elif _dict["role"] == "system":
            return SystemMessage(content=_dict["content"])
        else:
            return HumanMessage(content=_dict["content"])

    def generate(context) -> dict:
        payload = context.get_json()
        raw_messages = payload.get("messages", [])
        thread_id = payload.get("thread_id")
        messages = [convert_dict_to_message(_dict) for _dict in raw_messages]

        with PostgresSaver.from_conn_string(DB_URI) as saver:
            # Important: Ensure tables exist
            saver.setup()

            # Get the compiled agent from the closure
            agent = agent_closure(saver=saver)

            # Handle system message logic
            system_content = None
            if messages and messages[0].type == "system":
                system_content = messages[0].content
                del messages[0]

            config = {"configurable": {"thread_id": thread_id}} if thread_id else {}

            # If your get_graph_closure implementation handles system messages
            # via input state or constructor, adjust the invoke call here:
            generated_response = agent.invoke({"messages": messages}, config)

            return {
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "choices": [
                        {
                            "index": 0,
                            "message": get_formatted_message(
                                generated_response["messages"][-1]
                            ),
                        }
                    ]
                },
            }

    def generate_stream(context) -> Generator[dict, None, None]:
        headers = context.get_headers()
        is_assistant = headers.get("X-Ai-Interface") == "assistant"
        payload = context.get_json()
        raw_messages = payload.get("messages", [])
        thread_id = payload.get("thread_id")
        messages = [convert_dict_to_message(_dict) for _dict in raw_messages]

        with PostgresSaver.from_conn_string(DB_URI) as saver:
            saver.setup()
            agent = agent_closure(saver=saver)

            if messages and messages[0].type == "system":
                del messages[0]

            config = {"configurable": {"thread_id": thread_id}} if thread_id else {}
            response_stream = agent.stream(
                {"messages": messages}, config, stream_mode=["updates", "messages"]
            )

            for chunk_type, data in response_stream:
                msg_obj = None
                if chunk_type == "messages":
                    msg_obj = data[0]
                    if msg_obj.type == "tool":
                        continue
                elif chunk_type == "updates":
                    if "agent" in data:
                        msg_obj = data["agent"]["messages"][0]
                    elif "tools" in data:
                        msg_obj = data["tools"]["messages"][0]

                if msg_obj:
                    if message := get_formatted_message(
                        msg_obj, is_assistant=is_assistant
                    ):
                        yield {
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

    return generate, generate_stream
