import asyncio
import json
from collections.abc import Generator

from adk_agent.agent import APP_NAME, get_runner
from google.genai import types

USER_ID = "local_user"


def ai_stream_service(context, base_url=None, model_id=None):
    """Create a deployable AI service that runs the ADK agent and returns (generate, generate_stream).

    Builds the ADK runner once, then returns two callables: one for a single
    non-streaming response and one that streams agent updates (tool calls and
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
    runner = get_runner(model_id=model_id, base_url=base_url)

    def _extract_user_content(payload: dict) -> str:
        """Extract the last user message content from the payload."""
        messages = payload.get("messages", [])
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    async def _run_agent(user_content: str) -> list:
        """Run the agent asynchronously and collect all events."""
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID
        )

        new_message = types.Content(
            role="user", parts=[types.Part.from_text(text=user_content)]
        )

        events = []
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=new_message,
        ):
            events.append(event)

        return events

    def _format_event(event) -> dict | None:
        """Turn an ADK event into a display dict (role + content) for the client."""
        if not event.content or not event.content.parts:
            return None

        for part in event.content.parts:
            if part.function_call:
                return {
                    "role": "assistant",
                    "content": f"Calling tool '{part.function_call.name}' with args: {json.dumps(dict(part.function_call.args) if part.function_call.args else {})}",
                }
            if part.function_response:
                response_data = (
                    dict(part.function_response.response)
                    if part.function_response.response
                    else {}
                )
                return {
                    "role": "tool",
                    "content": f"\nTool Output:\n {json.dumps(response_data)}",
                }
            if part.text:
                role = event.content.role or "model"
                if role == "model":
                    return {"role": "assistant", "content": part.text}

        return None

    def generate(context) -> dict:
        """Run the agent once on the context payload and return a single response dict."""
        payload = context.get_json()
        user_content = _extract_user_content(payload)

        events = asyncio.get_event_loop().run_until_complete(_run_agent(user_content))

        # Extract final model response
        final_content = ""
        for event in reversed(events):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text and (event.content.role or "model") == "model":
                        final_content = part.text
                        break
                if final_content:
                    break

        return {
            "headers": {"Content-Type": "application/json"},
            "body": {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": final_content},
                    }
                ]
            },
        }

    def generate_stream(context) -> Generator[dict, None, None]:
        """Stream agent updates as choice deltas from the context payload."""
        payload = context.get_json()
        user_content = _extract_user_content(payload)

        events = asyncio.get_event_loop().run_until_complete(_run_agent(user_content))

        for event in events:
            message = _format_event(event)
            if message:
                yield {
                    "choices": [{"index": 0, "delta": message, "finish_reason": None}]
                }

    return generate, generate_stream
