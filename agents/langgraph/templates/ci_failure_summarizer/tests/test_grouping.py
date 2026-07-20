"""Tests for deterministic failure grouping and fingerprinting."""

from __future__ import annotations

import json
from pathlib import Path

from ci_failure_summarizer.grouping import (
    build_failure_record,
    build_fingerprint,
    extract_qg_label,
    group_failures,
    infer_failure_area,
)
from ci_failure_summarizer.models import FailureEvidence, LogFetchResult, WorkflowJob, WorkflowRun

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture() -> tuple[WorkflowRun, list[WorkflowJob]]:
    payload = json.loads((FIXTURES / "github_failure_run.json").read_text())
    run = WorkflowRun.from_api(payload["workflow_runs"][0])
    jobs = [
        WorkflowJob.from_api(job)
        for job in payload["jobs"][str(run.id)]["jobs"]
    ]
    return run, jobs


def test_extract_qg_label_from_workflow_name():
    assert extract_qg_label("QG4: Agent Deployment Integration Tests") == "QG4"


def test_infer_failure_area_for_health_check():
    assert infer_failure_area("test-agent (langgraph-react-agent)", "Health check") == "health-check"


def test_build_fingerprint_is_stable():
    first = build_fingerprint(
        workflow_name="QG4: Agent Deployment Integration Tests",
        job_name="test-agent (langgraph-react-agent)",
        failed_step="Health check",
        branch="main",
        event="schedule",
        qg_label="QG4",
        failure_area="health-check",
    )
    second = build_fingerprint(
        workflow_name="QG4: Agent Deployment Integration Tests",
        job_name="test-agent (langgraph-react-agent)",
        failed_step="Health check",
        branch="main",
        event="schedule",
        qg_label="QG4",
        failure_area="health-check",
    )
    assert first == second
    assert len(first) == 16


def test_group_failures_deduplicates_and_handles_missing_logs():
    run, jobs = _load_fixture()
    log_results = {
        222: LogFetchResult(
            job_id=222,
            available=False,
            status_code=403,
            error="Must have admin rights to Repository.",
        )
    }

    failures = group_failures(
        run=run,
        jobs=jobs,
        workflow_file="agent-deployment-test.yaml",
        log_results=log_results,
    )

    assert len(failures) == 1
    failure = failures[0]
    assert failure.job_name == "test-agent (langgraph-react-agent)"
    assert failure.failed_step == "Health check"
    assert failure.logs_available is False
    assert failure.metadata["failure_area"] == "health-check"
    assert failure.metadata["log_status_code"] == 403


def test_build_failure_record_attaches_typed_failure_evidence():
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
        name="langflow-simple-tool-calling-agent",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/example/jobs/222",
        steps=(),
    )
    excerpt = "\n".join(
        [
            "E integration.utils.RouteNotFoundError: No route found for langflow-simple-tool-calling-agent",
            'E oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
            "tests/integration/conftest.py:33: Failed",
        ]
    )
    log_result = LogFetchResult(
        job_id=222,
        available=True,
        status_code=200,
        excerpt=excerpt,
    )

    failure = build_failure_record(
        run=run,
        job=job,
        workflow_file="agent-deployment-test.yaml",
        log_result=log_result,
    )

    assert failure is not None
    assert isinstance(failure.evidence, FailureEvidence)
    assert failure.evidence.source == "github_job_log"
    assert failure.evidence.excerpt == excerpt
    assert failure.evidence.signature
    assert any("RouteNotFoundError" in marker for marker in failure.evidence.markers)
    assert "evidence_excerpt" not in failure.metadata
