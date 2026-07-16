"""Tests for GitHub client parsing and log degradation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from ci_failure_summarizer.github_client import (
    GitHubActionsClient,
    normalize_workflow_path,
    workflow_paths_match,
)
from ci_failure_summarizer.models import WorkflowJob

FIXTURES = Path(__file__).parent / "fixtures"


def test_resolve_workflow_file_preserves_dotgithub_prefix():
    """lstrip('./') would strip the leading dot from .github/workflows/... paths."""
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "workflows": [
            {
                "name": "QG4: Agent Deployment Integration Tests",
                "path": ".github/workflows/agent-deployment-test.yaml",
            }
        ]
    }
    client._request = MagicMock(return_value=response)  # type: ignore[method-assign]

    workflow_file = client.resolve_workflow_file(
        "QG4: Agent Deployment Integration Tests",
        "agent-deployment-test.yaml",
    )

    assert workflow_file == ".github/workflows/agent-deployment-test.yaml"


def test_normalize_workflow_path_strips_relative_prefix_only():
    assert (
        normalize_workflow_path("./.github/workflows/foo.yaml")
        == ".github/workflows/foo.yaml"
    )


def test_workflow_paths_match_accepts_basename_fallback():
    assert workflow_paths_match(
        "agent-deployment-test.yaml",
        ".github/workflows/agent-deployment-test.yaml",
    )


def test_request_surfaces_rate_limit_for_metadata_fetch():
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.ok = False
    response.status_code = 403
    response.headers = {
        "X-RateLimit-Remaining": "0",
        "Retry-After": "60",
    }
    response.json.return_value = {"message": "API rate limit exceeded"}
    client._session = MagicMock()
    client._session.request.return_value = response

    try:
        client.get_run(123456789)
    except RuntimeError as exc:
        assert "rate limit" in str(exc).lower()
        assert "60" in str(exc)
        assert "actions/runs/123456789" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_request_surfaces_not_found_for_missing_run():
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.ok = False
    response.status_code = 404
    response.headers = {}
    response.json.return_value = {"message": "Not Found"}
    client._session = MagicMock()
    client._session.request.return_value = response

    try:
        client.get_run(999)
    except RuntimeError as exc:
        assert "Not Found" in str(exc)
        assert "actions/runs/999" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


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
    response.ok = True
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
    response.ok = True
    response.json.return_value = payload["jobs"]["123456789"]
    client._session = MagicMock()
    client._session.request.return_value = response

    jobs = client.list_jobs(123456789)

    assert len(jobs) == 2
    assert jobs[1].name == "test-agent (langgraph-react-agent)"
    assert jobs[1].steps[-1].name == "Health check"


def test_get_latest_run_uses_workflow_basename_in_api_path():
    payload = json.loads((FIXTURES / "github_failure_run.json").read_text())
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"workflow_runs": payload["workflow_runs"]}
    client._session = MagicMock()
    client._session.request.return_value = response

    run = client.get_latest_run(".github/workflows/agent-deployment-test.yaml")

    assert run is not None
    request_url = client._session.request.call_args.args[1]
    assert request_url.endswith("/actions/workflows/agent-deployment-test.yaml/runs")


def test_get_latest_run_parses_fixture_payload():
    payload = json.loads((FIXTURES / "github_failure_run.json").read_text())
    client = GitHubActionsClient("red-hat-data-services/agentic-starter-kits")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"workflow_runs": payload["workflow_runs"]}
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
