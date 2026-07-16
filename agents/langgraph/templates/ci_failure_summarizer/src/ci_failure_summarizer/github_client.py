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


def _classify_log_fetch_error(response: requests.Response) -> str:
    """Map GitHub log-download failures to actionable, less misleading messages."""
    try:
        body = response.json()
        message = (body.get("message") or "").strip()
    except ValueError:
        message = ""

    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining == "0" or "rate limit" in message.lower():
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            return f"GitHub API rate limit exceeded (retry after {retry_after}s)"
        return "GitHub API rate limit exceeded"

    if response.status_code == 404:
        return message or "Job logs not found"

    if message:
        return message

    if response.status_code == 403:
        return "Job logs unavailable without repository admin access"

    return "Job logs unavailable"


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
        response.raise_for_status()
        return response

    def resolve_workflow_file(self, workflow_name: str, fallback_file: str) -> str:
        """Resolve workflow file path by display name, falling back to known QG4 file."""
        path = f"/repos/{self.repository}/actions/workflows"
        # Spike assumption: repository has <=100 workflows; no Link pagination yet.
        payload = self._request("GET", path, params={"per_page": 100}).json()
        for workflow in payload.get("workflows", []):
            if workflow.get("name") == workflow_name and workflow.get("path"):
                return workflow["path"].lstrip("./")
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
        path = f"/repos/{self.repository}/actions/workflows/{workflow_file}/runs"
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
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            return LogFetchResult(
                job_id=job_id,
                available=False,
                status_code=status,
                error=str(exc),
            )
        except requests.RequestException as exc:
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
