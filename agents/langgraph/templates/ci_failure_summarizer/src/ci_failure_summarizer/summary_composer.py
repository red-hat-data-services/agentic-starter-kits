"""Deterministic summary rendering for grouped CI failures."""

from __future__ import annotations

import re

from ci_failure_summarizer.failure_evidence import resolve_failure_evidence, select_best_error_marker
from ci_failure_summarizer.models import FailureRecord, Incident, WorkflowRun

_ROUTE_NOT_FOUND_RE = re.compile(
    r"RouteNotFoundError: No route found for (?P<route>[\w.-]+)|"
    r'routes\.route\.openshift\.io "(?P<route2>[^"]+)" not found',
    re.IGNORECASE,
)
_CONTAINER_ENV_VAR_RE = re.compile(r"\bCONTAINER_IMAGE(?:_[A-Z]+)?\b")


def compose_summary(
    *,
    run: WorkflowRun,
    failures: list[FailureRecord],
    incidents: list[Incident],
) -> str:
    if not failures:
        return (
            f"No failed jobs found for workflow run #{run.id} "
            f"({run.html_url})."
        )
    incident_by_fp = {incident.fingerprint: incident for incident in incidents}
    lines = [
        f"*CI Triage Summary* — {run.name}",
        f"*Run:* <{run.html_url}|#{run.id}> ({run.event} on `{run.head_branch}`)",
        "",
        "*Deterministic findings*",
    ]
    for failure in failures:
        step = failure.failed_step or "unknown step"
        area = failure.metadata.get("failure_area")
        area_suffix = f" [{area}]" if area else ""
        incident = incident_by_fp.get(failure.fingerprint)
        count = incident.occurrence_count if incident else 1
        assessment = _classify_failure(failure, incident)
        lines.extend(
            [
                f"- `{failure.job_name}` failed at `{step}`{area_suffix} (fingerprint `{failure.fingerprint}`, seen {count}x)",
                f"  Cause: {assessment['cause']}",
                f"  Evidence: {assessment['evidence']}",
                f"  Recommendation: {assessment['recommendation']}",
            ]
        )
    return "\n".join(lines)


def _first_meaningful_line(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _source_label(failure: FailureRecord, evidence) -> str:
    if failure.logs_available:
        return "current run logs"
    prior_run = evidence.run_id if evidence else None
    if prior_run:
        return f"prior occurrence run #{prior_run}"
    return "prior occurrence logs"


def _classify_failure(
    failure: FailureRecord,
    incident: Incident | None,
) -> dict[str, str]:
    evidence = resolve_failure_evidence(failure, incident)
    markers = list(evidence.markers) if evidence else []
    excerpt = evidence.excerpt if evidence else ""
    haystack = "\n".join(markers + ([excerpt] if excerpt else []))
    evidence_line = select_best_error_marker(markers) or (
        _first_meaningful_line(excerpt) or "No deterministic evidence markers extracted."
    )
    source = _source_label(failure, evidence)

    route_match = _ROUTE_NOT_FOUND_RE.search(haystack)
    if route_match:
        route_name = route_match.group("route") or route_match.group("route2") or failure.job_name
        return {
            "cause": "The pre-deployed agent route was missing, so the integration test could not resolve the expected endpoint.",
            "evidence": f"{source}: {evidence_line}",
            "recommendation": f"Verify route `{route_name}` exists in `ci-testing`, or update the test/deployment wiring to use the actual route name.",
        }

    env_vars = sorted(set(_CONTAINER_ENV_VAR_RE.findall(haystack)))
    if env_vars:
        rendered_vars = ", ".join(f"`{name}`" for name in env_vars)
        return {
            "cause": "Required deployment environment variables were missing, so the build/deploy path aborted before the health check.",
            "evidence": f"{source}: {evidence_line}",
            "recommendation": f"Set {rendered_vars} in `.env` or CI before running the integration test again.",
        }

    if markers and failure.logs_available:
        return {
            "cause": "Deterministic error markers were extracted from the current failed-step log section, but no specific rule matched yet.",
            "evidence": f"{source}: {evidence_line}",
            "recommendation": "Inspect the evidence excerpt and add a deterministic rule for this failure family.",
        }

    if markers:
        return {
            "cause": "Current logs were unavailable; this summary is using persisted evidence from a prior matching fingerprint.",
            "evidence": f"{source}: {evidence_line}",
            "recommendation": "Confirm the current run matches the persisted evidence before taking action.",
        }

    if failure.logs_available:
        return {
            "cause": "Logs were available, but no deterministic evidence markers were extracted from the failed-step section.",
            "evidence": f"{source}: {evidence_line}",
            "recommendation": "Inspect the failed-step excerpt and add a deterministic parser rule for this failure family.",
        }

    return {
        "cause": "No authenticated logs or persisted evidence were available; triage is metadata-only and limited to workflow/job metadata.",
        "evidence": "metadata only",
        "recommendation": "Retry with GitHub log access or inspect the workflow run manually.",
    }
