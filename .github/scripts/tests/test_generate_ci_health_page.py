#!/usr/bin/env python3
"""Tests for the CI health dashboard generator."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_ci_health_page import (  # noqa: E402
    WORKFLOWS,
    WorkflowRun,
    compute_pass_rate,
    is_relevant_run,
    main,
    render_workflow_card,
    summaries_from_api,
    summaries_from_fixture,
    summarize_workflow,
    unavailable_workflow_summary,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ci-runs-sample.json"


def test_fixture_loads_all_workflows():
    summaries = summaries_from_fixture(FIXTURE)
    assert len(summaries) == 4
    assert summaries[0].display_name == "Code Quality"
    assert summaries[0].latest is not None
    assert summaries[0].latest.conclusion == "success"


def test_qg4_latest_failure_is_surfaced():
    summaries = summaries_from_fixture(FIXTURE)
    qg4 = next(
        item for item in summaries if item.workflow_file == "agent-deployment-test.yaml"
    )
    assert qg4.latest is not None
    assert qg4.latest.conclusion == "failure"


def test_pass_rate_ignores_pull_requests():
    now = datetime.now(UTC)
    earlier = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    later = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = [
        WorkflowRun(
            id=1,
            name="Code Quality",
            event="pull_request",
            head_branch="feature",
            status="completed",
            conclusion="failure",
            html_url="https://example.com/1",
            created_at=earlier,
            updated_at=later,
            run_started_at=earlier,
        ),
        WorkflowRun(
            id=2,
            name="Code Quality",
            event="push",
            head_branch="main",
            status="completed",
            conclusion="success",
            html_url="https://example.com/2",
            created_at=later,
            updated_at=(now - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            run_started_at=later,
        ),
    ]
    rate, total, passed = compute_pass_rate(runs, days=7)
    assert total == 1
    assert passed == 1
    assert rate == 100.0


def test_workflow_dispatch_on_feature_branch_is_ignored():
    run = WorkflowRun(
        id=3,
        name="Code Quality",
        event="workflow_dispatch",
        head_branch="feature-branch",
        status="completed",
        conclusion="success",
        html_url="https://example.com/3",
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        updated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert is_relevant_run(run) is False


def test_schedule_run_is_always_relevant():
    run = WorkflowRun(
        id=4,
        name="QG4: Agent Deployment Integration Tests",
        event="schedule",
        head_branch="",
        status="completed",
        conclusion="success",
        html_url="https://example.com/4",
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        updated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert is_relevant_run(run) is True


def test_empty_workflow_summary():
    summary = summarize_workflow(WORKFLOWS[0], [])
    assert summary.latest is None
    assert summary.pass_rate_7d is None
    assert summary.recent_runs == ()


def test_unavailable_workflow_renders_error_card():
    summary = unavailable_workflow_summary(
        WORKFLOWS[2],
        "GitHub API error 404 for /repos/example/actions/workflows/eval-gating.yml/runs",
    )
    card = render_workflow_card(summary)
    assert "Data unavailable" in card
    assert "Inner Loop Gating" in card
    assert "404" in card


def test_summaries_from_api_continues_after_workflow_failure(monkeypatch):
    class FakeClient:
        def list_workflow_runs(self, workflow_file: str) -> list[WorkflowRun]:
            if workflow_file == "eval-gating.yml":
                raise RuntimeError("GitHub API error 404")
            return []

    monkeypatch.setattr(
        "generate_ci_health_page.GitHubActionsClient",
        lambda token, repository: FakeClient(),
    )

    summaries = summaries_from_api(
        "red-hat-data-services/agentic-starter-kits", "token"
    )
    assert len(summaries) == 4
    gating = next(item for item in summaries if item.workflow_file == "eval-gating.yml")
    assert gating.error_message is not None
    assert "404" in gating.error_message
    assert all(item.error_message is None for item in summaries if item != gating)


def test_main_writes_html(tmp_path):
    output = tmp_path / "index.html"
    assert main(["--input", str(FIXTURE), "--output", str(output)]) == 0
    content = output.read_text(encoding="utf-8")
    assert "agentic-starter-kits CI Health" in content
    assert "QG4: Agent Deployment Integration Tests" in content
