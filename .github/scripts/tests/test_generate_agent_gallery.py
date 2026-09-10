#!/usr/bin/env python3
"""Tests for the agent gallery homepage generator."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_agent_gallery import (  # noqa: E402
    collect_agents,
    main,
    render_gallery,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GITHUB_REACT = (
    "https://github.com/red-hat-data-services/agentic-starter-kits/tree/main/"
    "agents/langgraph/templates/react_agent"
)
CI_HEALTH_PAGES_WORKFLOW = (
    Path(__file__).resolve().parents[2] / "workflows" / "ci-health-pages.yml"
)


def _write_agent(
    root: Path,
    rel_dir: str,
    *,
    display_name: str | None = "Demo Agent",
) -> None:
    agent_dir = root / rel_dir
    agent_dir.mkdir(parents=True)
    lines = ["name: demo-agent"]
    if display_name is not None:
        lines.append(f'displayName: "{display_name}"')
    lines.extend(
        [
            "framework: langgraph",
            'description: "A demo kit for tests."',
            'labels: ["tool-calling"]',
        ]
    )
    (agent_dir / "agent.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_collect_includes_react_agent():
    agents = collect_agents(REPO_ROOT)
    names = {a.display_name for a in agents}
    assert "LangGraph ReAct Agent" in names


def test_card_links_to_github_not_local_docs():
    html = render_gallery(collect_agents(REPO_ROOT))
    assert GITHUB_REACT in html
    assert "mkdocs" not in html.lower()


def test_gallery_does_not_inline_readme_bodies():
    html = render_gallery(collect_agents(REPO_ROOT))
    readme = (
        REPO_ROOT / "agents" / "langgraph" / "templates" / "react_agent" / "README.md"
    )
    snippet = readme.read_text(encoding="utf-8").splitlines()[2]
    assert snippet not in html


def test_render_includes_search_and_framework_filters():
    html = render_gallery(collect_agents(REPO_ROOT))
    assert 'id="kit-search"' in html
    assert 'data-framework="langgraph"' in html
    assert "View on GitHub" in html
    assert ".card[hidden]" in html
    assert "display: none" in html


def test_skips_agent_without_display_name(tmp_path):
    _write_agent(tmp_path, "agents/langgraph/templates/ok")
    _write_agent(tmp_path, "agents/langgraph/templates/no_name", display_name=None)
    agents = collect_agents(tmp_path)
    assert [a.rel_path for a in agents] == ["agents/langgraph/templates/ok"]


def test_skips_claude_worktrees(tmp_path):
    _write_agent(tmp_path, "agents/langgraph/templates/ok")
    _write_agent(
        tmp_path,
        ".claude/worktrees/scratch/agents/langgraph/templates/clone",
    )
    agents = collect_agents(tmp_path)
    assert [a.rel_path for a in agents] == ["agents/langgraph/templates/ok"]


def test_main_writes_gallery(tmp_path):
    output = tmp_path / "index.html"
    assert main(["--repo-root", str(REPO_ROOT), "--output", str(output)]) == 0
    content = output.read_text(encoding="utf-8")
    assert "Agentic starter kits" in content
    assert GITHUB_REACT in content
    assert "ci-health/" in content


def test_ci_health_pages_workflow_builds_gallery_then_dashboard():
    text = CI_HEALTH_PAGES_WORKFLOW.read_text(encoding="utf-8")
    assert "generate_agent_gallery.py" in text
    assert "--output site/index.html" in text
    assert "site/ci-health/index.html" in text
    assert "generate_ci_health_page.py --output site/index.html" not in text
