#!/usr/bin/env python3
"""Tests for the agent discovery script."""

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from discover_agents import discover_agents

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a minimal fake repo with two agent.yaml files."""
    agent_a = tmp_path / "agents" / "framework_a" / "templates" / "agent_one"
    agent_a.mkdir(parents=True)
    (agent_a / "agent.yaml").write_text(
        dedent("""\
        name: framework-a-agent-one
        displayName: "Framework A Agent One"
        framework: framework_a
        description: "First test agent."
        env:
          required:
            - API_KEY
    """)
    )

    agent_b = tmp_path / "agents" / "framework_b" / "templates" / "agent_two"
    agent_b.mkdir(parents=True)
    (agent_b / "agent.yaml").write_text(
        dedent("""\
        name: framework-b-agent-two
        displayName: "Framework B Agent Two"
        framework: framework_b
        description: "Second test agent."
    """)
    )
    return tmp_path


def test_discover_finds_all_agents(fake_repo):
    agents = discover_agents(str(fake_repo))
    assert len(agents) == 2
    names = {a["name"] for a in agents}
    assert names == {"framework-a-agent-one", "framework-b-agent-two"}


def test_discover_extracts_required_fields(fake_repo):
    agents = discover_agents(str(fake_repo))
    agent = next(a for a in agents if a["name"] == "framework-a-agent-one")
    assert agent["displayName"] == "Framework A Agent One"
    assert agent["description"] == "First test agent."
    assert agent["framework"] == "framework_a"
    assert agent["path"] == "agents/framework_a/templates/agent_one"


def test_discover_sorts_by_name(fake_repo):
    agents = discover_agents(str(fake_repo))
    names = [a["name"] for a in agents]
    assert names == sorted(names)


def test_discover_skips_dirs_without_agent_yaml(fake_repo):
    no_yaml = fake_repo / "agents" / "framework_c" / "templates" / "no_agent"
    no_yaml.mkdir(parents=True)
    (no_yaml / "README.md").write_text("not an agent")
    agents = discover_agents(str(fake_repo))
    assert len(agents) == 2


def test_discover_real_repo():
    """Verify discovery works against the actual repo."""
    agents = discover_agents(str(REPO_ROOT))
    assert len(agents) >= 11
    names = {a["name"] for a in agents}
    assert "langgraph-react-agent" in names
    assert "crewai-websearch-agent" in names
    for agent in agents:
        assert all(
            k in agent
            for k in ("name", "displayName", "description", "framework", "path")
        )


def test_cli_outputs_json():
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "discover_agents.py"),
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) >= 11
