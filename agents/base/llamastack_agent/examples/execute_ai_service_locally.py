"""
Run LlamaStack agent locally (stub or real LlamaStack API).

Usage:
  From repo root with PYTHONPATH including agents/base/llamastack_agent:
    python -m agents.base.llamastack_agent.examples.execute_ai_service_locally

  Or after cd agents/base/llamastack_agent and PYTHONPATH=/app:/app/src:
    uvicorn main:app --reload
    # Then POST /chat with {"message": "Hello"}
"""

import asyncio
import os

# Ensure we can import the agent and utils
if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from llamastack_agent_base.agent import get_agent_closure
from llamastack_agent_base.utils import get_env_var


async def main():
    base_url = get_env_var("BASE_URL")
    model_id = get_env_var("MODEL_ID")
    get_agent = get_agent_closure(base_url=base_url, model_id=model_id)
    agent = get_agent()
    result = await agent.run(input=[{"role": "user", "content": "Hello, LlamaStack!"}])
    print("Response:", result)


if __name__ == "__main__":
    asyncio.run(main())
