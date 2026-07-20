"""Tests for summarizer orchestration robustness."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from ci_failure_summarizer.config import SummarizerConfig
from ci_failure_summarizer.models import Incident, WorkflowJob, WorkflowRun
from ci_failure_summarizer.orchestrator import SummarizerOrchestrator


def _failed_run() -> WorkflowRun:
    return WorkflowRun(
        id=123,
        name="QG4: Agent Deployment Integration Tests",
        event="schedule",
        head_branch="main",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/repo/actions/runs/123",
        created_at="2026-07-15T02:30:00Z",
        path=".github/workflows/agent-deployment-test.yaml",
    )


def _failed_job() -> WorkflowJob:
    return WorkflowJob(
        id=222,
        name="test-agent (langgraph-react-agent)",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/jobs/222",
        steps=(),
    )


def _config() -> SummarizerConfig:
    return SummarizerConfig(
        repository="red-hat-data-services/agentic-starter-kits",
        workflow_name="QG4: Agent Deployment Integration Tests",
        slack_webhook_url="https://hooks.slack.com/services/test",
        github_token=None,
        model_id="test-model",
        base_url="http://localhost:8080/v1",
        api_key="test-key",
    )


def test_run_records_summary_when_slack_delivery_fails():
    run = _failed_run()
    job = _failed_job()
    incident = Incident(
        id=1,
        fingerprint="abc123",
        workflow_name=run.name,
        workflow_file="agent-deployment-test.yaml",
        job_name=job.name,
        failed_step=None,
        branch=run.head_branch,
        event=run.event,
        qg_label="QG4",
        occurrence_count=1,
    )

    github = MagicMock()
    github.resolve_workflow_file.return_value = "agent-deployment-test.yaml"
    github.get_latest_run.return_value = run
    github.list_jobs.return_value = [job]
    github.is_failed_job.return_value = True
    github.fetch_job_logs.return_value = MagicMock(
        available=False, excerpt=None, status_code=403
    )

    store = MagicMock()
    store.upsert_failures.return_value = [incident]

    orchestrator = SummarizerOrchestrator(
        config=_config(),
        incident_store=store,
        github_client=github,
    )

    with (
        patch(
            "ci_failure_summarizer.orchestrator.compose_summary",
            return_value="*CI Triage Summary* — test summary",
        ),
        patch(
            "ci_failure_summarizer.orchestrator.maybe_post_summary",
            return_value=(False, "Slack delivery failed: HTTP 500"),
        ),
    ):
        result = orchestrator.run()

    assert result.summary_text == "*CI Triage Summary* — test summary"
    assert result.slack_posted is False
    assert result.slack_skipped_reason == "Slack delivery failed: HTTP 500"
    store.record_summary.assert_called_once()
    call_kwargs = store.record_summary.call_args.kwargs
    assert call_kwargs["run_id"] == run.id
    assert call_kwargs["summary_text"] == "*CI Triage Summary* — test summary"
    assert call_kwargs["slack_posted"] is False
    assert call_kwargs["metadata"]["slack_skipped_reason"] == (
        "Slack delivery failed: HTTP 500"
    )


def test_run_records_failure_evidence_in_summary_metadata():
    run = _failed_run()
    job = _failed_job()
    incident = Incident(
        id=1,
        fingerprint="abc123",
        workflow_name=run.name,
        workflow_file="agent-deployment-test.yaml",
        job_name=job.name,
        failed_step=None,
        branch=run.head_branch,
        event=run.event,
        qg_label="QG4",
        occurrence_count=1,
    )

    github = MagicMock()
    github.resolve_workflow_file.return_value = "agent-deployment-test.yaml"
    github.get_latest_run.return_value = run
    github.list_jobs.return_value = [job]
    github.is_failed_job.return_value = True
    github.failed_step_name.return_value = "Run integration test"
    github.fetch_job_logs.return_value = MagicMock(
        available=True,
        excerpt=(
            "integration.utils.RouteNotFoundError: No route found for "
            "langflow-simple-tool-calling-agent"
        ),
        status_code=200,
        error=None,
    )

    store = MagicMock()
    store.upsert_failures.return_value = [incident]

    orchestrator = SummarizerOrchestrator(
        config=_config(),
        incident_store=store,
        github_client=github,
    )

    with (
        patch(
            "ci_failure_summarizer.orchestrator.compose_summary",
            return_value="*CI Triage Summary* — test summary",
        ),
        patch(
            "ci_failure_summarizer.orchestrator.maybe_post_summary",
            return_value=(False, "SLACK_WEBHOOK_URL is not configured"),
        ),
    ):
        orchestrator.run()

    call_kwargs = store.record_summary.call_args.kwargs
    evidence = call_kwargs["metadata"]["failure_evidence"]
    assert evidence
    fingerprint, details = next(iter(evidence.items()))
    assert fingerprint
    assert details["job_name"] == job.name
    assert details["evidence_signature"]
    assert "RouteNotFoundError" in details["primary_marker"]
    assert "evidence_excerpt" not in details
    assert "evidence_markers" not in details


def test_run_rejects_explicit_run_id_from_unrelated_workflow():
    wrong_run = WorkflowRun(
        id=999,
        name="Code Quality",
        event="push",
        head_branch="main",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/repo/actions/runs/999",
        created_at="2026-07-15T03:00:00Z",
        path=".github/workflows/code-quality.yml",
    )

    github = MagicMock()
    github.resolve_workflow_file.return_value = "agent-deployment-test.yaml"
    github.get_run.return_value = wrong_run

    orchestrator = SummarizerOrchestrator(
        config=_config(),
        incident_store=MagicMock(),
        github_client=github,
    )

    with pytest.raises(ValueError, match="Run 999 is not from workflow"):
        orchestrator.run(run_id=999)


def test_run_accepts_explicit_run_id_for_configured_workflow():
    run = _failed_run()
    job = _failed_job()

    github = MagicMock()
    github.resolve_workflow_file.return_value = "agent-deployment-test.yaml"
    github.get_run.return_value = run
    github.list_jobs.return_value = [job]
    github.is_failed_job.return_value = True
    github.fetch_job_logs.return_value = MagicMock(
        available=False, excerpt=None, status_code=403
    )

    store = MagicMock()
    store.upsert_failures.return_value = []

    orchestrator = SummarizerOrchestrator(
        config=_config(),
        incident_store=store,
        github_client=github,
    )

    with (
        patch(
            "ci_failure_summarizer.orchestrator.compose_summary",
            return_value="summary",
        ),
        patch(
            "ci_failure_summarizer.orchestrator.maybe_post_summary",
            return_value=(False, "SLACK_WEBHOOK_URL is not configured"),
        ),
    ):
        result = orchestrator.run(run_id=run.id)

    github.get_run.assert_called_once_with(run.id)
    github.get_latest_run.assert_not_called()
    assert result.run_id == run.id


def test_run_records_summary_when_latest_run_did_not_fail():
    run = WorkflowRun(
        id=456,
        name="QG4: Agent Deployment Integration Tests",
        event="schedule",
        head_branch="main",
        status="completed",
        conclusion="success",
        html_url="https://github.com/example/repo/actions/runs/456",
        created_at="2026-07-15T02:30:00Z",
        path=".github/workflows/agent-deployment-test.yaml",
    )

    github = MagicMock()
    github.resolve_workflow_file.return_value = (
        ".github/workflows/agent-deployment-test.yaml"
    )
    github.get_latest_run.return_value = run

    store = MagicMock()

    orchestrator = SummarizerOrchestrator(
        config=_config(),
        incident_store=store,
        github_client=github,
    )

    result = orchestrator.run()

    assert result.failures == []
    assert result.slack_skipped_reason == "latest run did not fail"
    store.upsert_failures.assert_not_called()
    store.record_summary.assert_called_once()
    call_kwargs = store.record_summary.call_args.kwargs
    assert call_kwargs["run_id"] == run.id
    assert call_kwargs["slack_posted"] is False
    assert call_kwargs["metadata"]["slack_skipped_reason"] == "latest run did not fail"
