"""
Query a deployed agent instance via HTTP.
Useful for testing OpenShift/Kubernetes deployments.
"""
import requests
import uuid
from examples._interactive_chat import InteractiveChat

# Update this with your deployed route URL
DEPLOYMENT_URL = "https://your-route-url.com/chat"
thread_id = "PLACEHOLDER FOR YOUR THREAD ID"
stream = False  # Set to True if your deployment supports streaming

if thread_id == "PLACEHOLDER FOR YOUR THREAD ID":
    thread_id = str(uuid.uuid4())

header = f" thread_id: {thread_id} "
print()
print("\u2554" + len(header) * "\u2550" + "\u2557")
print("\u2551" + header + "\u2551")
print("\u255a" + len(header) * "\u2550" + "\u255d")
print()


def ai_service_invoke(payload):
    """
    Send request to deployed agent endpoint.

    Args:
        payload: Dictionary with "messages" key containing message list

    Returns:
        Response from the deployed agent
    """
    payload["thread_id"] = thread_id

    try:
        response = requests.post(
            DEPLOYMENT_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error querying deployment: {e}")
        return {"choices": [{"message": {"role": "assistant", "content": f"Error: {e}"}}]}


# Note: Streaming not yet implemented for HTTP queries
# Use stream=False for now
chat = InteractiveChat(ai_service_invoke, stream=False)
chat.run()
