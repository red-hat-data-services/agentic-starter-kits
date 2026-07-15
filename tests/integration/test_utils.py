from __future__ import annotations

from pathlib import Path

import pytest

from integration import utils as integration_utils

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("test_file", "expected_agent_dir"),
    [
        (
            "agents/langgraph/templates/react_agent/tests/integration/test_deployment.py",
            "agents/langgraph/templates/react_agent",
        ),
        (
            "agents/langgraph/templates/react_agent/tests/integration/test_auth.py",
            "agents/langgraph/templates/react_agent",
        ),
        (
            "agents/langgraph/templates/human_in_the_loop/tests/integration/test_deployment.py",
            "agents/langgraph/templates/human_in_the_loop",
        ),
        (
            "agents/langgraph/templates/agentic_rag/tests/integration/conftest.py",
            "agents/langgraph/templates/agentic_rag",
        ),
        (
            "agents/google/templates/adk/tests/integration/test_deployment.py",
            "agents/google/templates/adk",
        ),
        (
            "agents/crewai/templates/websearch_agent/tests/integration/test_deployment.py",
            "agents/crewai/templates/websearch_agent",
        ),
    ],
)
def test_resolve_agent_dir_returns_agent_root(test_file: str, expected_agent_dir: str):
    resolved = integration_utils.resolve_agent_dir(REPO_ROOT / test_file)

    assert resolved == REPO_ROOT / expected_agent_dir


def test_resolve_agent_dir_rejects_non_agent_paths():
    with pytest.raises(FileNotFoundError, match="agent.yaml"):
        integration_utils.resolve_agent_dir(REPO_ROOT / "tests/integration/conftest.py")
