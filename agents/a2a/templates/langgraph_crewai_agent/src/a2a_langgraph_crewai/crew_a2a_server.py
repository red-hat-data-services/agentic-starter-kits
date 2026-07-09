"""
CrewAI agent exposed as an A2A server (JSON-RPC over HTTP via a2a-sdk).

Run: uv run python -m a2a_langgraph_crewai.crew_a2a_server
OpenShift: PORT=8080 (set by platform); local default CREW_A2A_PORT=9100.
"""

from __future__ import annotations

import asyncio
import logging
from os import getenv

import uvicorn
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from crewai import LLM, Agent, Crew, Task
from dotenv import load_dotenv
from starlette.applications import Starlette

from .custom_tool import DummyWebSearchTool
from .tracing import enable_tracing_crewai, wrap_func_with_mlflow_trace

logger = logging.getLogger(__name__)

_llm: LLM | None = None


def _listen_port() -> int:
    """OpenShift sets PORT=8080; locally use CREW_A2A_PORT (default 9100)."""
    if p := getenv("PORT"):
        return int(p)
    return int(getenv("CREW_A2A_PORT", "9100"))


def _ensure_llm() -> LLM:
    global _llm
    if _llm is not None:
        return _llm
    base_url = getenv("BASE_URL")
    model_id = getenv("MODEL_ID")
    api_key = getenv("API_KEY", "no-key")
    if not base_url or not model_id:
        raise RuntimeError("BASE_URL and MODEL_ID must be set (see template.env).")
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    _llm = LLM(
        model=f"openai/{model_id}",
        base_url=base_url,
        api_key=api_key,
        temperature=0.2,
    )
    return _llm


def _run_crew(user_prompt: str) -> str:
    llm = _ensure_llm()
    tools = [DummyWebSearchTool()]
    # Manual tool tracing: mlflow.crewai.autolog() does not capture tool spans
    # in newer CrewAI versions (>=1.10). If a future version fixes this, remove
    # the manual wrapping below to avoid duplicate tool spans.
    for tool in tools:
        tool._run = wrap_func_with_mlflow_trace(
            tool._run, span_type="tool", name=tool.name
        )

    specialist = Agent(
        role="Specialist",
        goal="Answer clearly. For questions needing web facts, use Web Search and ground your answer in its result.",
        backstory=(
            "You are a concise expert. Respond in plain text without role-playing headers. "
            "When the user asks for cluster hosting, enterprise Kubernetes, or similar factual look-ups, "
            "call Web Search once and incorporate the snippet faithfully."
        ),
        tools=tools,
        llm=llm,
        verbose=False,
        max_iter=5,
    )
    task = Task(
        description=user_prompt,
        expected_output="A direct, helpful answer.",
        agent=specialist,
    )
    crew = Crew(agents=[specialist], tasks=[task], verbose=False)
    return str(crew.kickoff())


class CrewA2AExecutor(AgentExecutor):
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        text = context.get_user_input()
        if not text.strip():
            await event_queue.enqueue_event(
                new_text_message("Error: empty user message.")
            )
            return
        try:
            result = await asyncio.to_thread(_run_crew, text)
            await event_queue.enqueue_event(new_text_message(result))
        except Exception:  # noqa: BLE001
            logger.exception("Crew kickoff failed")
            await event_queue.enqueue_event(
                new_text_message("CrewAI error: request failed.")
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported in this demo")


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="[CREW] %(levelname)s:%(name)s:%(message)s",
    )
    enable_tracing_crewai()

    public_base = getenv("CREW_A2A_PUBLIC_URL", "http://127.0.0.1:9100").rstrip("/")
    port = _listen_port()

    skill = AgentSkill(
        id="crew_specialist",
        name="CrewAI specialist",
        description="CrewAI agent with a dummy Web Search tool (custom_tool.py).",
        tags=["crewai", "text"],
        examples=[
            "Explain what A2A is in one paragraph.",
            "What is the best cluster hosting service?",
        ],
    )

    agent_card = AgentCard(
        name="CrewAI A2A Specialist",
        description="Minimal CrewAI agent speaking the A2A protocol.",
        supported_interfaces=[
            AgentInterface(
                url=f"{public_base}/",
                protocol_binding="JSONRPC",
            ),
        ],
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
    )

    handler = DefaultRequestHandler(
        agent_executor=CrewA2AExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    routes = []
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url="/"))
    app = Starlette(routes=routes)
    logger.info("Crew A2A listening on 0.0.0.0:%s (public_base=%s)", port, public_base)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
