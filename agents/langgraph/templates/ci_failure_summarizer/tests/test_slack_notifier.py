"""Tests for Slack payload composition."""

from __future__ import annotations

from unittest.mock import patch

from ci_failure_summarizer.grouping import group_failures
from ci_failure_summarizer.models import WorkflowJob, WorkflowRun
from ci_failure_summarizer.slack_notifier import (
    build_slack_payload,
    maybe_post_summary,
)


def test_build_slack_payload_includes_summary_and_links():
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
    payload = build_slack_payload(
        repository="red-hat-data-services/agentic-starter-kits",
        run=run,
        summary_text="*Likely cause*\n- metadata-only triage",
        failures=failures,
        dashboard_url="https://red-hat-data-services.github.io/agentic-starter-kits/",
    )

    text_blob = str(payload)
    assert "CI Triage Summary" in text_blob
    assert "langgraph-react-agent" in text_blob
    assert "metadata-only triage" in text_blob
    assert "https://github.com/example/repo/actions/runs/123" in text_blob
    assert "red-hat-data-services.github.io/agentic-starter-kits" in text_blob


def test_maybe_post_summary_returns_failure_reason_without_raising():
    with patch(
        "ci_failure_summarizer.slack_notifier.post_summary",
        side_effect=RuntimeError("Slack webhook returned HTTP 500"),
    ):
        posted, reason = maybe_post_summary(
            webhook_url="https://hooks.slack.com/services/test",
            payload={"text": "summary"},
        )

    assert posted is False
    assert reason is not None
    assert "Slack delivery failed" in reason
