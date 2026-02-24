"""
Agent without any agentic framework: OpenAI client and pure Python.

Uses only the official OpenAI Python client (openai package) and Responses API.
No LlamaStack, LangChain, LlamaIndex, etc. - to show it can be done without frameworks.
Compatible with OpenAI API and any OpenAI-compatible endpoint (e.g. base_url override).
"""

import asyncio
import csv
import inspect
import re
from io import StringIO
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from openai_responses_agent_base.utils import get_env_var
from openai_responses_agent_base.tools import search_price, search_reviews


def get_agent_closure(
    base_url: Optional[str] = None,
    model_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Callable:
    """
    Return a callable that creates an agent instance (adapter with async run() for main.py).
    """
    if not base_url:
        base_url = get_env_var("BASE_URL")
    if not model_id:
        model_id = get_env_var("MODEL_ID")
    if not api_key:
        try:
            api_key = get_env_var("API_KEY")
        except (EnvironmentError, ValueError):
            api_key = None

    def get_agent() -> "_AIAgentAdapter":
        return _AIAgentAdapter(
            base_url=base_url,
            model_id=model_id,
            api_key=api_key,
            tools=[("search_price", search_price), ("search_reviews", search_reviews)],
        )

    return get_agent


class _AIAgentAdapter:
    """
    Adapter that exposes async run(input) for main.py, delegating to AIAgent.query().
    """

    def __init__(
        self,
        base_url: str,
        model_id: str,
        api_key: Optional[str] = None,
        tools: Optional[List[tuple]] = None,
    ):
        self._base_url = base_url
        self._model_id = model_id
        self._api_key = api_key
        self._tools = tools or []

    async def run(self, input: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run the agent on the given messages; uses AIAgent.query() with the last user message.
        """
        question = ""
        if input:
            last = input[-1]
            question = last.get("content", "") if isinstance(last, dict) else str(last)

        agent = AIAgent(
            model=self._model_id,
            base_url=self._base_url,
            api_key=self._api_key,
        )

        for name, func in self._tools:
            agent.register_tool(name, func)

        answer = await asyncio.to_thread(agent.query, question)
        if answer is None:
            answer = ""

        response_messages = list(input)
        response_messages.append({"role": "assistant", "content": answer})
        return {"messages": response_messages, "finish_reason": "stop"}


def _messages_to_responses_input(messages: List[Dict]) -> tuple[str, List[Dict]]:
    """
    Convert chat-style messages to Responses API format.
    Returns (instructions, input_items) where instructions is the system content
    and input_items is a list of {role, content} with content as [{type: 'input_text', text: '...'}].
    """
    instructions = ""
    input_items: List[Dict] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "") or ""
        text_content = [{"type": "input_text", "text": content}]
        if role == "system":
            instructions = content
            continue
        input_items.append({"role": role, "content": text_content})
    return instructions, input_items


def _get_output_text_from_response(response: Any) -> str:
    """Extract assistant text from Responses API response (response.output[].content[])."""
    if not getattr(response, "output", None) or not response.output:
        return ""
    for item in response.output:
        content = getattr(item, "content", None) or []
        for block in content:
            if getattr(block, "type", None) == "output_text":
                return getattr(block, "text", None) or ""
            # some SDKs may expose .text directly
            if hasattr(block, "text"):
                return block.text or ""
    return ""


class AIAgent:
    """
    Agent using only OpenAI client and pure Python: Responses API, no agentic framework.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the agent with tools and OpenAI client configuration.

        Args:
            model: Model identifier (e.g. "gpt-4o-mini" or provider-specific id).
            temperature: Sampling temperature (0 = deterministic).
            base_url: Optional API base URL (for OpenAI-compatible endpoints).
            api_key: Optional API key (required for OpenAI; can be None for some local endpoints).
        """
        load_dotenv()

        if base_url is None:
            base_url = get_env_var("BASE_URL")
        if model is None:
            model = get_env_var("MODEL_ID")
        if api_key is None:
            try:
                api_key = get_env_var("API_KEY")
            except (EnvironmentError, ValueError):
                api_key = None

        # OpenAI client: works with api.openai.com or any OpenAI-compatible API (base_url)
        client_kwargs: Dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url.rstrip("/")
        if api_key:
            client_kwargs["api_key"] = api_key

        self.client = OpenAI(**client_kwargs)
        self.model = model
        self.temperature = temperature
        self.tools: Dict[str, Callable] = {}
        self.messages: List[Dict] = []
        self.action_re = re.compile(r"Action:\s*(\w+)\s*\((.*?)\)")

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the chat history."""
        self.messages.append({"role": role, "content": content})

    def register_tool(self, name: str, func: Callable) -> None:
        """Register a tool that the agent can use."""
        self.tools[name] = func

    def _function_to_string(self, func: Callable) -> str:
        """Convert a function to its source code string."""
        return inspect.getsource(func)

    def _parse_arguments(self, args_str: str) -> List[str]:
        """Parse comma-separated arguments handling quoted strings."""
        reader = csv.reader(StringIO(args_str))
        args = next(reader)
        return [arg.strip().strip("'\"") for arg in args]

    def _responses_create(
        self,
        messages: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ):
        """
        Single Responses API call via OpenAI client.

        Args:
            messages: List of messages; if None, self.messages is used.
            temperature: Override temperature for this call.
            model: Override model for this call.

        Returns:
            Response from client.responses.create (object with .output etc.).
        """
        msg_list = messages if messages is not None else self.messages
        temp = temperature if temperature is not None else self.temperature
        model_id = model if model is not None else self.model

        instructions, input_items = _messages_to_responses_input(msg_list)
        kwargs: Dict[str, Any] = {
            "model": model_id,
            "instructions": instructions,
            "input": input_items,
        }
        if temp != 0:
            kwargs["temperature"] = temp

        return self.client.responses.create(**kwargs)

    def _execute(self) -> str:
        """Execute a Responses API request."""
        response = self._responses_create(
            messages=self.messages,
            temperature=self.temperature,
            model=self.model,
        )
        return _get_output_text_from_response(response)

    def query(self, question: str, max_turns: int = 10) -> Optional[str]:
        """
        Process a question through multiple turns until getting final answer.

        Args:
            question: The input question to process.
            max_turns: Maximum number of turns before timing out.

        Returns:
            The final answer or None if no answer found.
        """
        self.setup_system_prompt()
        next_prompt = question

        try:
            for _ in range(max_turns):
                self.messages.append({"role": "user", "content": next_prompt})
                result = self._execute()
                self.messages.append({"role": "assistant", "content": result})

                if result.lower().startswith("answer:"):
                    idx = result.lower().find("answer:")
                    return result[idx + len("answer:") :].strip()

                actions = [
                    m
                    for line in result.split("\n")
                    for m in [self.action_re.match(line)]
                    if m
                ]

                if actions:
                    action, args_str = actions[0].groups()
                    action_inputs = self._parse_arguments(args_str)

                    tool = self.tools.get(action)
                    if not tool:
                        raise ValueError(f"Unknown action: {action}")

                    observation = tool(*action_inputs)
                    next_prompt = f"Observation: {observation}"
                else:
                    # No Action: line – treat the whole response as the final answer
                    return result.strip() if result else None

        except Exception:
            return None

        return None

    def setup_system_prompt(self) -> None:
        """Set up the system prompt with available tools."""
        prompt = """
        You run in a loop of Thought, Suggestions, Action, PAUSE, Observation.
        At the end of the loop you output an Answer
        Use Thought to describe your thoughts about the question you have been asked.
        Use Action to run one of the suitable actions available to you - then return
        PAUSE.
        Observation will be the result of running those actions.

        Your available actions are:
        {}

        Example session:

        [Question: How much does a Lenovo Laptop costs?
        Thought: I should look the Laptop price using get_average_price

        Action: get_average_price("Lenovo")
        PAUSE

        You will be called again with this:

        Observation: A lenovo laptop average price is $400

        You then output:

        Answer: A lenovo laptop costs $400
        ,
        Questions: How much does a Lenovo Laptop costs and what are the reviews?
        Thought: I need to find out both the price and the reviews for a Lenovo laptop. I will first search for the price and then look for the reviews.

        Action: search_price("Lenovo")
        PAUSE
        -- running search_price ['Lenovo']
        Observation: Price of Lenovo is $400
        Result: Action: search_reviews("Lenovo")
        PAUSE
        -- running search_reviews ['Lenovo']
        Observation: Reviews of Lenovo are good
        Result: Answer: A Lenovo laptop costs $400 and the reviews are good.
        Final answer: A Lenovo laptop costs $400 and the reviews are good.]

        """.strip()

        actions_str = [self._function_to_string(func) for func in self.tools.values()]
        system = prompt.format("\n\n".join(actions_str))
        self.messages = [{"role": "system", "content": system}]
