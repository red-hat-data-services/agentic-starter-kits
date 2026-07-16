"""Shared data models for CI failure ingest and summarization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    name: str
    event: str
    head_branch: str
    status: str
    conclusion: str | None
    html_url: str
    created_at: str
    workflow_id: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> WorkflowRun:
        return cls(
            id=payload["id"],
            name=payload.get("name") or "workflow run",
            event=payload.get("event") or "unknown",
            head_branch=payload.get("head_branch") or "",
            status=payload.get("status") or "unknown",
            conclusion=payload.get("conclusion"),
            html_url=payload.get("html_url") or "",
            created_at=payload.get("created_at") or "",
            workflow_id=payload.get("workflow_id"),
        )


@dataclass(frozen=True)
class JobStep:
    name: str
    status: str
    conclusion: str | None
    number: int

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> JobStep:
        return cls(
            name=payload.get("name") or f"step-{payload.get('number', 0)}",
            status=payload.get("status") or "unknown",
            conclusion=payload.get("conclusion"),
            number=int(payload.get("number") or 0),
        )


@dataclass(frozen=True)
class WorkflowJob:
    id: int
    name: str
    status: str
    conclusion: str | None
    html_url: str
    steps: tuple[JobStep, ...] = ()

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> WorkflowJob:
        steps = tuple(JobStep.from_api(step) for step in payload.get("steps") or [])
        return cls(
            id=payload["id"],
            name=payload.get("name") or "job",
            status=payload.get("status") or "unknown",
            conclusion=payload.get("conclusion"),
            html_url=payload.get("html_url") or "",
            steps=steps,
        )


@dataclass(frozen=True)
class LogFetchResult:
    job_id: int
    available: bool
    status_code: int | None = None
    excerpt: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class FailureRecord:
    workflow_name: str
    workflow_file: str
    run_id: int
    run_url: str
    event: str
    branch: str
    job_id: int
    job_name: str
    job_url: str
    failed_step: str | None
    qg_label: str | None
    fingerprint: str
    logs_available: bool = False
    log_excerpt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Incident:
    id: int | None
    fingerprint: str
    workflow_name: str
    workflow_file: str | None
    job_name: str
    failed_step: str | None
    branch: str | None
    event: str | None
    qg_label: str | None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    occurrence_count: int = 1
    latest_run_id: int | None = None
    latest_run_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SummaryResult:
    run_id: int
    run_url: str
    workflow_name: str
    failures: list[FailureRecord]
    incidents: list[Incident]
    summary_text: str
    slack_posted: bool
    slack_skipped_reason: str | None = None
    logs_available: bool = False
