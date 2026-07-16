"""Unauthenticated GitHub Actions ingest with graceful log degradation."""

from __future__ import annotations

import logging
from typing import Any

import requests

from ci_failure_summarizer.models import LogFetchResult, WorkflowJob, WorkflowRun

logger = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
FAILED_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out"})
LOG_EXCERPT_MAX_CHARS = 4000


def _extract_github_message(response: requests.Response) -> str:
    try:
        body = response.json()
        return (body.get("message") or "").strip()
    except ValueError:
        return ""


def _is_rate_limited(response: requests.Response, message: str) -> bool:
    remaining = response.headers.get("X-RateLimit-Remaining")
    return remaining == "0" or "rate limit" in message.lower()


def _format_rate_limit_message(response: requests.Response) -> str:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        return f"GitHub API rate limit exceeded (retry after {retry_after}s)"
    return "GitHub API rate limit exceeded"


def _classify_api_error(response: requests.Response, *, operation: str) -> str:
    """Map GitHub metadata API failures to actionable messages."""
    message = _extract_github_message(response)
    if _is_rate_limited(response, message):
        return f"{_format_rate_limit_message(response)} while {operation}"
    if response.status_code == 404:
        detail = message or "resource not found"
        return f"GitHub {detail} while {operation}"
    if message:
        return (
            f"GitHub API error ({response.status_code}) while {operation}: {message}"
        )
    return f"GitHub API request failed ({response.status_code}) while {operation}"


def _classify_log_fetch_error(response: requests.Response) -> str:
    """Map GitHub log-download failures to actionable, less misleading messages."""
    message = _extract_github_message(response)

    if _is_rate_limited(response, message):
        return _format_rate_limit_message(response)

    if response.status_code == 404:
        return message or "Job logs not found"

    if message:
        return message

    if response.status_code == 403:
        return "Job logs unavailable without repository admin access"

    return "Job logs unavailable"


def normalize_workflow_path(path: str) -> str:
    """Normalize workflow file paths from GitHub API or config."""
    return path.removeprefix("./")


def workflow_paths_match(expected_file: str, actual_path: str | None) -> bool:
    """Return True when run/workflow paths refer to the same workflow file."""
    if not actual_path:
        return False
    expected = normalize_workflow_path(expected_file)
    actual = normalize_workflow_path(actual_path)
    if expected == actual:
        return True
    return expected.rsplit("/", 1)[-1] == actual.rsplit("/", 1)[-1]


def workflow_api_ref(workflow_file: str) -> str:
    """Return the workflow file basename accepted by GitHub workflow endpoints."""
    return workflow_file.rsplit("/", 1)[-1]


class GitHubActionsClient:
    """Fetch public GitHub Actions metadata; degrade when logs require auth."""

    def __init__(self, repository: str, token: str | None = None) -> None:
        self.repository = repository
        self._session = requests.Session()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ci-failure-summarizer",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._session.headers.update(headers)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_statuses: frozenset[int] | None = None,
    ) -> requests.Response:
        url = f"{API_ROOT}{path}"
        response = self._session.request(
            method, url, params=params, timeout=30
        )
        if allow_statuses and response.status_code in allow_statuses:
            return response
        if not response.ok:
            raise RuntimeError(
                _classify_api_error(
                    response,
                    operation=f"{method} {path}",
                )
            )
        return response

    def resolve_workflow_file(self, workflow_name: str, fallback_file: str) -> str:
        """Resolve workflow file path by display name, falling back to known QG4 file."""
        path = f"/repos/{self.repository}/actions/workflows"
        # Spike assumption: repository has <=100 workflows; no Link pagination yet.
        payload = self._request("GET", path, params={"per_page": 100}).json()
        for workflow in payload.get("workflows", []):
            if workflow.get("name") == workflow_name and workflow.get("path"):
                return normalize_workflow_path(workflow["path"])
        logger.warning(
            "Workflow %r not found via API; using fallback file %s",
            workflow_name,
            fallback_file,
        )
        return fallback_file

    def get_run(self, run_id: int) -> WorkflowRun:
        path = f"/repos/{self.repository}/actions/runs/{run_id}"
        payload = self._request("GET", path).json()
        return WorkflowRun.from_api(payload)

    def get_latest_run(self, workflow_file: str) -> WorkflowRun | None:
        workflow_ref = workflow_api_ref(workflow_file)
        path = f"/repos/{self.repository}/actions/workflows/{workflow_ref}/runs"
        payload = self._request("GET", path, params={"per_page": 1}).json()
        runs = payload.get("workflow_runs") or []
        if not runs:
            return None
        return WorkflowRun.from_api(runs[0])

    def list_jobs(self, run_id: int, *, per_page: int = 100) -> list[WorkflowJob]:
        path = f"/repos/{self.repository}/actions/runs/{run_id}/jobs"
        # Spike assumption: QG4 runs have <=100 jobs; no Link pagination yet.
        payload = self._request("GET", path, params={"per_page": per_page}).json()
        return [WorkflowJob.from_api(job) for job in payload.get("jobs") or []]

    def fetch_job_logs(self, job_id: int) -> LogFetchResult:
        path = f"/repos/{self.repository}/actions/jobs/{job_id}/logs"
        try:
            response = self._request(
                "GET",
                path,
                allow_statuses=frozenset({403, 404}),
            )
        except requests.RequestException as exc:
            return LogFetchResult(
                job_id=job_id,
                available=False,
                error=str(exc),
            )
        except RuntimeError as exc:
            return LogFetchResult(
                job_id=job_id,
                available=False,
                error=str(exc),
            )

        if response.status_code in {403, 404}:
            message = _classify_log_fetch_error(response)
            logger.info(
                "Job %s logs unavailable (HTTP %s): %s",
                job_id,
                response.status_code,
                message,
            )
            return LogFetchResult(
                job_id=job_id,
                available=False,
                status_code=response.status_code,
                error=message,
            )

        text = response.text or ""
        excerpt = text[-LOG_EXCERPT_MAX_CHARS:] if len(text) > LOG_EXCERPT_MAX_CHARS else text
        return LogFetchResult(
            job_id=job_id,
            available=True,
            status_code=response.status_code,
            excerpt=excerpt.strip() or None,
        )

    @staticmethod
    def is_failed_job(job: WorkflowJob) -> bool:
        return job.conclusion in FAILED_CONCLUSIONS

    @staticmethod
    def failed_step_name(job: WorkflowJob) -> str | None:
        failed_steps = [
            step.name
            for step in job.steps
            if step.conclusion in FAILED_CONCLUSIONS
        ]
        if failed_steps:
            return failed_steps[-1]
        if job.conclusion in FAILED_CONCLUSIONS:
            return job.name
        return None
