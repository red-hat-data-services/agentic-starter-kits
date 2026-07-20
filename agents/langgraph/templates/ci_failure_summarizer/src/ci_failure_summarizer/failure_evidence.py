"""Shared failure evidence extraction, ranking, and resolution helpers."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any, TypedDict

from ci_failure_summarizer.models import FailureEvidence, FailureRecord, Incident

LOG_EXCERPT_MAX_CHARS = 4000
_GROUP_START_RE = re.compile(r"##\[group\]")
_ERROR_LINE_RE = re.compile(
    r"##\[error\]|traceback|assertionerror|exception|error from server|failed:|error:",
    re.IGNORECASE,
)
_POST_JOB_RE = re.compile(r"post job cleanup", re.IGNORECASE)
_TIMESTAMP_PREFIX_RE = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T[0-9:.]+Z\s*")
_GENERIC_WRAPPER_RE = re.compile(
    r"pytest\.fail\(|ERROR tests/|Process completed with exit code|During handling of the above exception",
    re.IGNORECASE,
)


def _truncate_excerpt(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if len(text) > LOG_EXCERPT_MAX_CHARS:
        return text[-LOG_EXCERPT_MAX_CHARS:]
    return text


def extract_relevant_log_excerpt(
    text: str,
    *,
    failed_step: str | None,
) -> str | None:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines:
        return None

    failed_step_idx = None
    if failed_step:
        failed_step_lower = failed_step.lower()
        for idx, line in enumerate(lines):
            if failed_step_lower in line.lower():
                failed_step_idx = idx
                break

    error_idx = None
    for idx in range(len(lines) - 1, -1, -1):
        if _ERROR_LINE_RE.search(lines[idx]):
            error_idx = idx
            break

    if error_idx is None:
        return _truncate_excerpt(text)

    if failed_step_idx is not None and failed_step_idx <= error_idx:
        start = failed_step_idx
    else:
        start = max(0, error_idx - 80)
        for idx in range(error_idx, max(-1, error_idx - 200), -1):
            if _GROUP_START_RE.search(lines[idx]):
                start = idx
                break

    end = min(len(lines), error_idx + 1)
    for idx in range(error_idx + 1, len(lines)):
        if _GROUP_START_RE.search(lines[idx]) or _POST_JOB_RE.search(lines[idx]):
            end = idx
            break
        end = idx + 1

    return _truncate_excerpt("\n".join(lines[start:end]))


def _normalize_log_line(line: str) -> str:
    return _TIMESTAMP_PREFIX_RE.sub("", line).strip()


def _score_error_marker(marker: str) -> tuple[int, int]:
    score = 0
    lower = marker.lower()
    if _GENERIC_WRAPPER_RE.search(marker):
        score -= 100
    if "container_image" in lower:
        score += 120
    if "routenotfounderror" in lower or "routes.route.openshift.io" in lower:
        score += 120
    if "error from server" in lower:
        score += 30
    if "failed:" in lower:
        score += 20
    if "exception" in lower:
        score += 10
    return score, len(marker)


def select_best_error_marker(markers: list[str]) -> str | None:
    if not markers:
        return None
    return max(markers, key=_score_error_marker)


def extract_error_markers(text: str, *, limit: int = 5) -> list[str]:
    markers: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = _normalize_log_line(raw_line)
        if not line or not _ERROR_LINE_RE.search(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        markers.append(line)
    markers.sort(key=_score_error_marker, reverse=True)
    return markers[:limit]


def build_evidence_signature(
    markers: list[str],
    *,
    fallback_excerpt: str | None = None,
) -> str | None:
    payload_parts = markers or ([fallback_excerpt] if fallback_excerpt else [])
    normalized = [part.strip().lower() for part in payload_parts if part and part.strip()]
    if not normalized:
        return None
    return sha256("|".join(normalized).encode("utf-8")).hexdigest()[:16]


def build_failure_evidence(
    excerpt: str | None,
    *,
    source: str,
    run_id: int | None,
) -> FailureEvidence | None:
    trimmed = _truncate_excerpt(excerpt or "")
    if not trimmed:
        return None
    markers = tuple(extract_error_markers(trimmed))
    return FailureEvidence(
        source=source,
        excerpt=trimmed,
        markers=markers,
        signature=build_evidence_signature(list(markers), fallback_excerpt=trimmed),
        run_id=run_id,
    )


def evidence_to_metadata(evidence: FailureEvidence) -> dict[str, Any]:
    return {
        "evidence_source": evidence.source,
        "evidence_excerpt": evidence.excerpt,
        "evidence_markers": list(evidence.markers),
        "evidence_signature": evidence.signature,
        "evidence_run_id": evidence.run_id,
    }


def evidence_from_metadata(metadata: dict[str, Any] | None) -> FailureEvidence | None:
    if not metadata:
        return None
    excerpt = str(metadata.get("evidence_excerpt") or "").strip()
    markers = tuple(
        marker
        for marker in (str(value).strip() for value in metadata.get("evidence_markers") or [])
        if marker
    )
    signature = metadata.get("evidence_signature")
    source = str(metadata.get("evidence_source") or "").strip() or "unknown"
    run_id = metadata.get("evidence_run_id")
    if not any([excerpt, markers, signature]):
        return None
    if run_id is not None:
        run_id = int(run_id)
    return FailureEvidence(
        source=source,
        excerpt=excerpt,
        markers=markers,
        signature=str(signature) if signature else build_evidence_signature(list(markers), fallback_excerpt=excerpt),
        run_id=run_id,
    )


def merge_failure_evidence(
    primary: FailureEvidence | None,
    fallback: FailureEvidence | None,
) -> FailureEvidence | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    excerpt = primary.excerpt or fallback.excerpt
    markers = primary.markers or fallback.markers
    signature = primary.signature or fallback.signature or build_evidence_signature(
        list(markers),
        fallback_excerpt=excerpt,
    )
    return FailureEvidence(
        source=primary.source or fallback.source,
        excerpt=excerpt,
        markers=markers,
        signature=signature,
        run_id=primary.run_id or fallback.run_id,
    )


def resolve_failure_evidence(
    failure: FailureRecord,
    incident: Incident | None,
) -> FailureEvidence | None:
    current = failure.evidence
    if current is None and failure.log_excerpt:
        current = build_failure_evidence(
            failure.log_excerpt,
            source="github_job_log",
            run_id=failure.run_id,
        )
    historical = evidence_from_metadata(incident.metadata if incident else None)
    return merge_failure_evidence(current, historical)


class FailureEvidenceSnapshot(TypedDict):
    job_name: str
    failed_step: str | None
    evidence_signature: str | None
    primary_marker: str | None
    evidence_source: str
    evidence_run_id: int | None


def build_failure_evidence_snapshot(
    *,
    failure: FailureRecord,
    evidence: FailureEvidence,
) -> FailureEvidenceSnapshot:
    return {
        "job_name": failure.job_name,
        "failed_step": failure.failed_step,
        "evidence_signature": evidence.signature,
        "primary_marker": select_best_error_marker(list(evidence.markers)),
        "evidence_source": evidence.source,
        "evidence_run_id": evidence.run_id,
    }


def build_summary_failure_evidence(
    failures: list[FailureRecord],
    incidents: list[Incident],
) -> dict[str, FailureEvidenceSnapshot]:
    incident_by_fp = {incident.fingerprint: incident for incident in incidents}
    evidence_by_fp: dict[str, FailureEvidenceSnapshot] = {}
    for failure in failures:
        evidence = resolve_failure_evidence(
            failure,
            incident_by_fp.get(failure.fingerprint),
        )
        if evidence is None:
            continue
        evidence_by_fp[failure.fingerprint] = build_failure_evidence_snapshot(
            failure=failure,
            evidence=evidence,
        )
    return evidence_by_fp
