from _interactive_chat import InteractiveChat
from ai_service import ai_stream_service
from langgraph_react_agent_base.utils import get_env_var


class SimpleContext:
    """Simple context object for local execution that holds request payload and headers."""

    def __init__(self, payload=None):
        """Store the initial request payload (or an empty dict)."""
        self.request_payload_json = payload or {}

    def get_json(self):
        """Return the current request payload as a dict (e.g. messages for the agent)."""
        return self.request_payload_json

    def get_headers(self):
        """Return request headers; empty dict for local execution."""
        return {}


base_url = get_env_var("BASE_URL")
model_id = get_env_var("MODEL_ID")

# Ensure base_url ends with /v1 if provided
if base_url and not base_url.endswith("/v1"):
    base_url = base_url.rstrip("/") + "/v1"

stream = True
context = SimpleContext()
ai_service_resp_func = ai_stream_service(
    context=context, base_url=base_url, model_id=model_id
)[stream]


def ai_service_invoke(payload):
    """Run the AI service for one turn: set context from payload and return (stream or full) response."""
    context.request_payload_json = payload
    return ai_service_resp_func(context)


chat = InteractiveChat(ai_service_invoke, stream=stream)
chat.run()
