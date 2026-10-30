"""Tests for deterministic summary rendering."""

from __future__ import annotations

from ci_failure_summarizer.grouping import group_failures
from ci_failure_summarizer.models import Incident, WorkflowJob, WorkflowRun
from ci_failure_summarizer.summary_composer import compose_summary


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

    summary = compose_summary(run=run, failures=failures, incidents=incidents)

    assert "langgraph-react-agent" in summary
    assert "metadata-only" in summary.lower() or "unavailable" in summary.lower()
    assert "seen 2x" in summary


def test_compose_summary_is_deterministic_even_with_model_config():
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
            occurrence_count=1,
        )
    ]
    incidents[0].metadata = {
        "evidence_source": "github_job_log",
        "evidence_markers": [
            "E integration.utils.RouteNotFoundError: No route found for langflow-simple-tool-calling-agent",
            'E oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
        ],
        "evidence_excerpt": "\n".join(
            [
                "E integration.utils.RouteNotFoundError: No route found for langflow-simple-tool-calling-agent",
                'E oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
            ]
        ),
        "evidence_signature": "bf2e3c85934c6d11",
        "evidence_run_id": 123,
    }
    summary = compose_summary(
        run=run,
        failures=failures,
        incidents=incidents,
    )

    assert "CI Triage Summary" in summary
    assert "pre-deployed agent route" in summary.lower()


def test_compose_fallback_summary_uses_persisted_incident_evidence():
    run = WorkflowRun(
        id=456,
        name="QG4: Agent Deployment Integration Tests",
        event="schedule",
        head_branch="main",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/repo/actions/runs/456",
        created_at="2026-07-16T02:30:00Z",
    )
    job = WorkflowJob(
        id=333,
        name="langflow-simple-tool-calling-agent",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/jobs/333",
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
            metadata={
                "evidence_source": "github_job_log",
                "evidence_signature": "deadbeefcafebabe",
                "evidence_markers": [
                    "integration.utils.RouteNotFoundError: No route found for langflow-simple-tool-calling-agent",
                    'oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
                ],
                "evidence_excerpt": "\n".join(
                    [
                        "integration.utils.RouteNotFoundError: No route found for langflow-simple-tool-calling-agent",
                        'oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
                    ]
                ),
                "evidence_run_id": 123,
            },
        )
    ]

    summary = compose_summary(run=run, failures=failures, incidents=incidents)

    assert "pre-deployed agent route was missing" in summary.lower()
    assert "verify route" in summary.lower()
    assert "prior occurrence" in summary.lower()


def test_compose_fallback_summary_renders_missing_env_var_recommendation():
    run = WorkflowRun(
        id=789,
        name="QG4: Agent Deployment Integration Tests",
        event="schedule",
        head_branch="main",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/repo/actions/runs/789",
        created_at="2026-07-16T02:30:00Z",
    )
    job = WorkflowJob(
        id=444,
        name="a2a-langgraph-crewai",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/jobs/444",
        steps=(),
    )
    failures = group_failures(
        run=run,
        jobs=[job],
        workflow_file="agent-deployment-test.yaml",
    )
    incidents = [
        Incident(
            id=2,
            fingerprint=failures[0].fingerprint,
            workflow_name=run.name,
            workflow_file="agent-deployment-test.yaml",
            job_name=failures[0].job_name,
            failed_step=failures[0].failed_step,
            branch=run.head_branch,
            event=run.event,
            qg_label="QG4",
            occurrence_count=2,
            metadata={
                "evidence_source": "github_job_log",
                "evidence_signature": "46e512ce8b01f3a8",
                "evidence_markers": [
                    "E Failed: Deployment failed: make build failed (exit 2)",
                    "E ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH in .env",
                ],
                "evidence_excerpt": "\n".join(
                    [
                        "E Failed: Deployment failed: make build failed (exit 2)",
                        "E ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH in .env",
                    ]
                ),
                "evidence_run_id": 789,
            },
        )
    ]

    summary = compose_summary(run=run, failures=failures, incidents=incidents)

    assert "environment variable" in summary.lower()
    assert "`CONTAINER_IMAGE`" in summary
    assert "`CONTAINER_IMAGE_CREW`" in summary
    assert "`CONTAINER_IMAGE_LANGGRAPH`" in summary
    assert (
        "ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH in .env"
        in summary
    )
    assert 'pytest.fail(f"Deployment failed: {exc}")' not in summary
