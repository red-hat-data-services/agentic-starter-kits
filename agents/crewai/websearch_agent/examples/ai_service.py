from os import getenv

from crewai import LLM
from crewai.agents.parser import AgentAction, AgentFinish
from crewai.tools.tool_types import ToolResult
from crewai_web_search.crew import AssistanceAgents


def ai_stream_service(context, base_url=None, model_id=None):
    """Create a deployable AI service that runs the CrewAI web search crew.

    Builds the LLM once, then returns two callables:
      - generate: returns a single response dict
      - generate_stream: yields streaming choice dicts via step_callback

    Args:
        context: Object with get_json() used to read the request payload.
        base_url: LLM API base URL (OpenAI-compatible / llama-stack).
        model_id: LLM model id; will be prefixed with 'openai/'.

    Returns:
        Tuple (generate, generate_stream).
    """
    api_key = getenv("API_KEY", "no-key")

    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    llm = LLM(
        model=f"openai/{model_id}",
        base_url=base_url,
        api_key=api_key,
        temperature=0.7,
    )

    def get_formatted_message(
        crewai_step: AgentAction | AgentFinish | ToolResult,
    ) -> dict | None:
        """Turn a CrewAI step into a display dict (role + content) for the client."""
        if isinstance(crewai_step, AgentAction):
            return {"role": "assistant", "content": str(crewai_step.result)}
        elif isinstance(crewai_step, AgentFinish):
            return {"role": "assistant", "content": crewai_step.output}
        elif isinstance(crewai_step, ToolResult):
            return {"role": "tool", "content": str(crewai_step.result)}
        return None

    def _parse_inputs(context):
        payload = context.get_json()
        messages = payload.get("messages", [])
        user_question = messages[-1]["content"]
        custom_instruction = ""
        if messages and messages[0].get("role") == "system":
            custom_instruction = messages[0]["content"]
        return {
            "user_prompt": user_question,
            "custom_instruction": custom_instruction,
        }

    def generate(context) -> dict:
        """Run the crew and return a single response dict with choices."""
        inputs = _parse_inputs(context)

        result = AssistanceAgents(llm=llm).crew().kickoff(inputs=inputs)

        return {
            "headers": {"Content-Type": "application/json"},
            "body": {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": str(result)},
                    }
                ]
            },
        }

    def generate_stream(context):
        """Run the crew and yield streaming choice dicts as steps complete."""
        inputs = _parse_inputs(context)
        steps_collected = []

        def _on_step(step_output):
            steps_collected.append(step_output)

        result = (
            AssistanceAgents(llm=llm, step_callback=_on_step)
            .crew()
            .kickoff(inputs=inputs)
        )

        # Yield collected intermediate steps
        for step in steps_collected:
            msg = get_formatted_message(step)
            if msg:
                yield {"choices": [{"index": 0, "delta": msg, "finish_reason": None}]}

        # Yield final answer
        yield {
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": str(result)},
                    "finish_reason": "stop",
                }
            ]
        }

    return generate, generate_stream
