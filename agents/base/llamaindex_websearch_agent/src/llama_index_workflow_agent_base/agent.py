from typing import Callable

from llama_index.core.tools import FunctionTool
from llama_index.llms.openai_like import OpenAILike

from llama_index_workflow_agent_base.utils import get_env_var
from llama_index_workflow_agent_base.tools import dummy_web_search
from llama_index_workflow_agent_base.workflow import FunctionCallingAgent


def get_workflow_closure(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> Callable:
    """Workflow generator closure."""

    if not api_key:
        api_key = get_env_var("API_KEY")
    if not base_url:
        base_url = get_env_var("BASE_URL")
    if not model_id:
        model_id = get_env_var("MODEL_ID")

    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])

    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    tools = [FunctionTool.from_defaults(dummy_web_search)]
    default_system_prompt = "You are a helpful AI assistant, please respond to the user's query to the best of your ability!"
    context_window = 4096

    client = OpenAILike(
        model=model_id,
        api_key=api_key,
        api_base=base_url,
        context_window=context_window,  # Bypass model name validation for custom models
        is_chat_model=True,  # Use chat completions endpoint instead of completions
        is_function_calling_model=True,  # Enable function calling/tools support
    )

    def get_agent(system_prompt: str = default_system_prompt) -> FunctionCallingAgent:
        """Get compiled workflow with overwritten system prompt, if provided"""

        # Create instance of compiled workflow
        return FunctionCallingAgent(
            llm=client,
            tools=tools,
            system_prompt=system_prompt,
            timeout=120,
            verbose=False,
        )

    return get_agent
