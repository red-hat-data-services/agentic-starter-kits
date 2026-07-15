"""Smoke tests: verify a2a-sdk v1.x imports used by this agent resolve correctly."""


def test_server_imports():
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore

    assert all(
        [
            AgentExecutor,
            RequestContext,
            EventQueue,
            DefaultRequestHandler,
            create_agent_card_routes,
            create_jsonrpc_routes,
            InMemoryTaskStore,
        ]
    )


def test_type_imports():
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

    assert all([AgentCapabilities, AgentCard, AgentInterface, AgentSkill])


def test_helper_imports():
    from a2a.helpers import (
        get_artifact_text,
        get_message_text,
        get_stream_response_text,
        new_text_message,
    )

    assert all(
        [
            get_artifact_text,
            get_message_text,
            get_stream_response_text,
            new_text_message,
        ]
    )


def test_client_imports():
    from a2a.client import ClientConfig, create_client

    assert all([ClientConfig, create_client])


def test_module_crew_a2a_server():
    import a2a_langgraph_crewai.crew_a2a_server  # noqa: F401


def test_module_langgraph_a2a_server():
    import a2a_langgraph_crewai.langgraph_a2a_server  # noqa: F401


def test_module_a2a_reply():
    import a2a_langgraph_crewai.a2a_reply  # noqa: F401


def test_module_demo_client():
    import a2a_langgraph_crewai.demo_client  # noqa: F401
