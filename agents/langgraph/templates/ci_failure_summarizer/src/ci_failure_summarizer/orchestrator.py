"""Manual trigger orchestration for CI failure summarization."""

from __future__ import annotations

import logging

from ci_failure_summarizer.config import SummarizerConfig
from ci_failure_summarizer.github_client import (
    GitHubActionsClient,
    workflow_paths_match,
)
from ci_failure_summarizer.grouping import group_failures
from ci_failure_summarizer.incident_store import IncidentStore
from ci_failure_summarizer.models import SummaryResult, WorkflowRun
from ci_failure_summarizer.slack_notifier import build_slack_payload, maybe_post_summary
from ci_failure_summarizer.summary_composer import compose_summary

logger = logging.getLogger(__name__)


class SummarizerOrchestrator:
    """End-to-end ingest, grouping, persistence, summarization, and Slack posting."""

    def __init__(
        self,
        *,
        config: SummarizerConfig,
        incident_store: IncidentStore,
        github_client: GitHubActionsClient | None = None,
    ) -> None:
        self.config = config
        self.incident_store = incident_store
        self.github = github_client or GitHubActionsClient(
            config.repository,
            token=config.github_token,
        )

    def run(self, *, run_id: int | None = None) -> SummaryResult:
        workflow_file = self.github.resolve_workflow_file(
            self.config.workflow_name,
            self.config.workflow_file,
        )
        run = self._select_run(workflow_file, run_id=run_id)
        if run is None:
            raise RuntimeError(
                f"No workflow runs found for {self.config.workflow_name} "
                f"({workflow_file}) in {self.config.repository}"
            )

        if run.conclusion not in {"failure", "cancelled", "timed_out"}:
            summary_text = (
                f"Latest workflow run #{run.id} concluded with "
                f"`{run.conclusion or run.status}`; no triage summary posted."
            )
            return SummaryResult(
                run_id=run.id,
                run_url=run.html_url,
                workflow_name=run.name,
                failures=[],
                incidents=[],
                summary_text=summary_text,
                slack_posted=False,
                slack_skipped_reason="latest run did not fail",
            )

        jobs = self.github.list_jobs(run.id)
        log_results = {
            job.id: self.github.fetch_job_logs(job.id)
            for job in jobs
            if self.github.is_failed_job(job)
        }
        failures = group_failures(
            run=run,
            jobs=jobs,
            workflow_file=workflow_file,
            log_results=log_results,
        )
        incidents = self.incident_store.upsert_failures(failures)
        summary_text = compose_summary(
            config=self.config,
            run=run,
            failures=failures,
            incidents=incidents,
        )
        payload = build_slack_payload(
            repository=self.config.repository,
            run=run,
            summary_text=summary_text,
            failures=failures,
            dashboard_url=self.config.dashboard_url,
        )
        slack_posted, slack_skipped_reason = maybe_post_summary(
            webhook_url=self.config.slack_webhook_url,
            payload=payload,
        )
        logs_available = any(failure.logs_available for failure in failures)
        self.incident_store.record_summary(
            run_id=run.id,
            summary_text=summary_text,
            slack_posted=slack_posted,
            logs_available=logs_available,
            incident_fingerprints=[failure.fingerprint for failure in failures],
            metadata={
                "workflow_file": workflow_file,
                "slack_skipped_reason": slack_skipped_reason,
            },
        )
        return SummaryResult(
            run_id=run.id,
            run_url=run.html_url,
            workflow_name=run.name,
            failures=failures,
            incidents=incidents,
            summary_text=summary_text,
            slack_posted=slack_posted,
            slack_skipped_reason=slack_skipped_reason,
            logs_available=logs_available,
        )

    def _select_run(
        self,
        workflow_file: str,
        *,
        run_id: int | None,
    ) -> WorkflowRun | None:
        if run_id is not None:
            run = self.github.get_run(run_id)
            if not workflow_paths_match(workflow_file, run.path):
                raise ValueError(
                    f"Run {run_id} is not from workflow "
                    f"{self.config.workflow_name!r} ({workflow_file}); "
                    f"got path {run.path!r}"
                )
            return run
        return self.github.get_latest_run(workflow_file)
