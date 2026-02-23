"""
OpenAI Responses Agent Base – agent without any agentic framework.

Uses only the OpenAI Python client and pure Python (Responses API).
No LlamaStack, LangChain, LlamaIndex, etc. Compatible with OpenAI and OpenAI-compatible endpoints.
"""

from openai_responses_agent_base.agent import AIAgent, get_agent_closure
from openai_responses_agent_base.tools import search_reviews, search_price
from openai_responses_agent_base.utils import get_env_var

__all__ = [
    "get_agent_closure",
    "AIAgent",
    "search_reviews",
    "search_price",
    "get_env_var",
]
