"""Tests for summary fallback formatting."""

from __future__ import annotations

from ci_failure_summarizer.models import Incident, WorkflowRun
from ci_failure_summarizer.summary_composer import compose_fallback_summary
from ci_failure_summarizer.grouping import group_failures
from ci_failure_summarizer.models import WorkflowJob


def test_compose_fallback_summary_notes_missing_logs():
    run = WorkflowRun(
        id=123,
        name="QG4: Agent Deployment Integration Tests",
        event="schedule",
        head_branch="main",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/repo/actions/runs/123",
        created_at="2026-07-15T02:30:00Z",
    )
    job = WorkflowJob(
        id=222,
        name="test-agent (langgraph-react-agent)",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/jobs/222",
        steps=(),
    )
    failures = group_failures(
        run=run,
        jobs=[job],
        workflow_file="agent-deployment-test.yaml",
    )
    incidents = [
        Incident(
            id=1,
            fingerprint=failures[0].fingerprint,
            workflow_name=run.name,
            workflow_file="agent-deployment-test.yaml",
            job_name=failures[0].job_name,
            failed_step=failures[0].failed_step,
            branch=run.head_branch,
            event=run.event,
            qg_label="QG4",
            occurrence_count=2,
        )
    ]

    summary = compose_fallback_summary(run=run, failures=failures, incidents=incidents)

    assert "langgraph-react-agent" in summary
    assert "metadata-only" in summary.lower() or "unavailable" in summary.lower()
    assert "seen 2x" in summary
