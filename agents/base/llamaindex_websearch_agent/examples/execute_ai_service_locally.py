from _interactive_chat import InteractiveChat
from ai_service import ai_stream_service
from llama_index_workflow_agent_base.utils import get_env_var


class SimpleContext:
    """Simple context object for local execution"""

    def __init__(self, payload=None):
        self.request_payload_json = payload or {}

    def get_json(self):
        return self.request_payload_json

    def get_headers(self):
        return {}


base_url = get_env_var("BASE_URL")
model_id = get_env_var("MODEL_ID")

# Ensure base_url ends with /v1 if provided
if base_url and not base_url.endswith('/v1'):
    base_url = base_url.rstrip('/') + '/v1'

stream = True
context = SimpleContext()
ai_service_resp_func = ai_stream_service(
    context=context,
    base_url=base_url,
    model_id=model_id
)[stream]


def ai_service_invoke(payload):
    context.request_payload_json = payload
    return ai_service_resp_func(context)


chat = InteractiveChat(ai_service_invoke, stream=stream)
chat.run()
