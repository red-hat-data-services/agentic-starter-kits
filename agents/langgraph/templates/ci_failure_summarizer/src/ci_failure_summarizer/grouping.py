"""Deterministic failure fingerprinting outside the LLM layer."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from ci_failure_summarizer.github_client import GitHubActionsClient
from ci_failure_summarizer.models import (
    FailureRecord,
    LogFetchResult,
    WorkflowJob,
    WorkflowRun,
)

QG_LABEL_PATTERN = re.compile(r"\b(QG\d+)\b", re.IGNORECASE)
KNOWN_FAILURE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"health check", re.IGNORECASE), "health-check"),
    (re.compile(r"deploy", re.IGNORECASE), "deploy"),
    (re.compile(r"teardown|cleanup", re.IGNORECASE), "teardown"),
    (re.compile(r"timeout|timed out", re.IGNORECASE), "timeout"),
    (re.compile(r"connection|cluster", re.IGNORECASE), "connectivity"),
)


def extract_qg_label(workflow_name: str) -> str | None:
    match = QG_LABEL_PATTERN.search(workflow_name)
    return match.group(1).upper() if match else None


def infer_failure_area(job_name: str, failed_step: str | None) -> str | None:
    haystack = f"{job_name} {failed_step or ''}"
    for pattern, label in KNOWN_FAILURE_PATTERNS:
        if pattern.search(haystack):
            return label
    return None


def build_fingerprint(
    *,
    workflow_name: str,
    job_name: str,
    failed_step: str | None,
    branch: str,
    event: str,
    qg_label: str | None,
    failure_area: str | None,
) -> str:
    """Stable fingerprint from metadata available without authenticated logs."""
    parts = [
        workflow_name.strip().lower(),
        job_name.strip().lower(),
        (failed_step or "").strip().lower(),
        branch.strip().lower(),
        event.strip().lower(),
        (qg_label or "").strip().lower(),
        (failure_area or "").strip().lower(),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def build_failure_record(
    *,
    run: WorkflowRun,
    job: WorkflowJob,
    workflow_file: str,
    log_result: LogFetchResult | None = None,
) -> FailureRecord | None:
    if not GitHubActionsClient.is_failed_job(job):
        return None

    failed_step = GitHubActionsClient.failed_step_name(job)
    qg_label = extract_qg_label(run.name)
    failure_area = infer_failure_area(job.name, failed_step)
    fingerprint = build_fingerprint(
        workflow_name=run.name,
        job_name=job.name,
        failed_step=failed_step,
        branch=run.head_branch,
        event=run.event,
        qg_label=qg_label,
        failure_area=failure_area,
    )

    logs_available = bool(log_result and log_result.available)
    log_excerpt = log_result.excerpt if logs_available else None

    return FailureRecord(
        workflow_name=run.name,
        workflow_file=workflow_file,
        run_id=run.id,
        run_url=run.html_url,
        event=run.event,
        branch=run.head_branch,
        job_id=job.id,
        job_name=job.name,
        job_url=job.html_url,
        failed_step=failed_step,
        qg_label=qg_label,
        fingerprint=fingerprint,
        logs_available=logs_available,
        log_excerpt=log_excerpt,
        metadata={
            "failure_area": failure_area,
            "job_conclusion": job.conclusion,
            "log_status_code": log_result.status_code if log_result else None,
            "log_error": log_result.error if log_result else None,
        },
    )


def group_failures(
    *,
    run: WorkflowRun,
    jobs: Iterable[WorkflowJob],
    workflow_file: str,
    log_results: dict[int, LogFetchResult] | None = None,
) -> list[FailureRecord]:
    """Collect and deduplicate failure records for a workflow run."""
    log_results = log_results or {}
    grouped: dict[str, FailureRecord] = {}
    for job in jobs:
        record = build_failure_record(
            run=run,
            job=job,
            workflow_file=workflow_file,
            log_result=log_results.get(job.id),
        )
        if record is None:
            continue
        grouped[record.fingerprint] = record
    return list(grouped.values())
