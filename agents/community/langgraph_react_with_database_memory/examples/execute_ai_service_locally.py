from ai_service import ai_stream_service
from langgraph_react_with_database_memory_base.utils import get_env_var
from _interactive_chat import InteractiveChat
import uuid


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


thread_id = "PLACEHOLDER FOR YOUR THREAD ID"

stream = True

# Load environment variables
base_url = get_env_var("BASE_URL")
model_id = get_env_var("MODEL_ID")
api_key = get_env_var("API_KEY")

# Ensure base_url ends with /v1 if provided
if base_url and not base_url.endswith("/v1"):
    base_url = base_url.rstrip("/") + "/v1"

context = SimpleContext()
ai_service_resp_func = ai_stream_service(
    context=context, base_url=base_url, model_id=model_id, api_key=api_key
)[stream]

if thread_id == "PLACEHOLDER FOR YOUR THREAD ID":
    thread_id = str(uuid.uuid4())

header = f" thread_id: {thread_id} "
print()
print("\u2554" + len(header) * "\u2550" + "\u2557")
print("\u2551" + header + "\u2551")
print("\u255a" + len(header) * "\u2550" + "\u255d")
print()


def ai_service_invoke(payload):
    payload["thread_id"] = thread_id
    context.request_payload_json = payload
    return ai_service_resp_func(context)


chat = InteractiveChat(ai_service_invoke, stream=stream)
chat.run()
