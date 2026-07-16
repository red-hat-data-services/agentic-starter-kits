"""Tests for GitHub client parsing and log degradation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from ci_failure_summarizer.github_client import GitHubActionsClient
from ci_failure_summarizer.models import WorkflowJob

FIXTURES = Path(__file__).parent / "fixtures"


def test_fetch_job_logs_degrades_on_403():
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.status_code = 403
    response.headers = {}
    response.json.return_value = {
        "message": "Must have admin rights to Repository."
    }
    client._request = MagicMock(return_value=response)  # type: ignore[method-assign]

    result = client.fetch_job_logs(222)

    assert result.available is False
    assert result.status_code == 403
    assert "admin rights" in (result.error or "")


def test_fetch_job_logs_reports_rate_limit_on_403():
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.status_code = 403
    response.headers = {
        "X-RateLimit-Remaining": "0",
        "Retry-After": "42",
    }
    response.json.return_value = {
        "message": "API rate limit exceeded for user"
    }
    client._request = MagicMock(return_value=response)  # type: ignore[method-assign]

    result = client.fetch_job_logs(222)

    assert result.available is False
    assert result.status_code == 403
    assert "rate limit" in (result.error or "").lower()
    assert "42" in (result.error or "")


def test_fetch_job_logs_returns_excerpt_on_success():
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.status_code = 200
    response.text = "line1\nline2\nERROR: health check failed"
    client._request = MagicMock(return_value=response)  # type: ignore[method-assign]

    result = client.fetch_job_logs(222)

    assert result.available is True
    assert "health check failed" in (result.excerpt or "")


def test_list_jobs_parses_fixture_payload():
    payload = json.loads((FIXTURES / "github_failure_run.json").read_text())
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.json.return_value = payload["jobs"]["123456789"]
    response.raise_for_status = MagicMock()
    client._session = MagicMock()
    client._session.request.return_value = response

    jobs = client.list_jobs(123456789)

    assert len(jobs) == 2
    assert jobs[1].name == "test-agent (langgraph-react-agent)"
    assert jobs[1].steps[-1].name == "Health check"


def test_get_latest_run_parses_fixture_payload():
    payload = json.loads((FIXTURES / "github_failure_run.json").read_text())
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.json.return_value = {"workflow_runs": payload["workflow_runs"]}
    response.raise_for_status = MagicMock()
    client._session = MagicMock()
    client._session.request.return_value = response

    run = client.get_latest_run("agent-deployment-test.yaml")

    assert run is not None
    assert run.id == 123456789
    assert run.conclusion == "failure"


def test_failed_step_name_prefers_last_failed_step():
    from ci_failure_summarizer.models import JobStep

    job = WorkflowJob(
        id=1,
        name="test-agent",
        status="completed",
        conclusion="failure",
        html_url="https://example.test/job/1",
        steps=(
            JobStep(name="Deploy", status="completed", conclusion="success", number=1),
            JobStep(
                name="Health check",
                status="completed",
                conclusion="failure",
                number=2,
            ),
        ),
    )
    assert GitHubActionsClient.failed_step_name(job) == "Health check"
