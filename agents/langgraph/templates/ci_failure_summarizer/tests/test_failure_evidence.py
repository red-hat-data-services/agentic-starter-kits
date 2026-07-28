"""Direct unit tests for failure evidence extraction and resolution."""

from __future__ import annotations

from ci_failure_summarizer.failure_evidence import (
    build_failure_evidence,
    build_summary_failure_evidence,
    evidence_from_metadata,
    evidence_to_metadata,
    extract_error_markers,
    extract_relevant_log_excerpt,
    merge_failure_evidence,
    resolve_failure_evidence,
)
from ci_failure_summarizer.models import FailureEvidence, FailureRecord, Incident


def _sample_failure(*, log_excerpt: str | None = None) -> FailureRecord:
    return FailureRecord(
        workflow_name="QG4: Agent Deployment Integration Tests",
        workflow_file="agent-deployment-test.yaml",
        run_id=123456789,
        run_url="https://github.com/example/actions/runs/123456789",
        event="schedule",
        branch="main",
        job_id=222,
        job_name="test-agent (langgraph-react-agent)",
        job_url="https://github.com/example/jobs/222",
        failed_step="Run integration test",
        qg_label="QG4",
        fingerprint="fp-abc123",
        logs_available=bool(log_excerpt),
        log_excerpt=log_excerpt,
    )


def test_extract_relevant_log_excerpt_prefers_failed_step_and_stops_before_cleanup():
    log_text = "\n".join(
        [
            "2026-07-20T04:19:20.4451275Z ##[group]Run integration test",
            "2026-07-20T04:19:20.4451819Z pytest tests/integration/test_deployment.py",
            "2026-07-20T04:19:24.5216230Z > raise RouteNotFoundError(...)",
            "2026-07-20T04:19:24.5217171Z E integration.utils.RouteNotFoundError: No route found for langflow-simple-tool-calling-agent",
            '2026-07-20T04:19:24.5217971Z E oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
            "2026-07-20T04:19:24.5655062Z ##[error]Process completed with exit code 2.",
            "2026-07-20T04:19:24.9000000Z Post job cleanup.",
            "2026-07-20T04:19:24.9300000Z Removing includeIf entries pointing to credentials config files",
        ]
    )

    excerpt = extract_relevant_log_excerpt(
        log_text,
        failed_step="Run integration test",
    )

    assert excerpt is not None
    assert "pytest tests/integration/test_deployment.py" in excerpt
    assert "RouteNotFoundError" in excerpt
    assert "Post job cleanup." not in excerpt
    assert "Removing includeIf entries" not in excerpt


def test_extract_error_markers_deduplicates_and_ranks_specific_errors_first():
    wrapper = "E Failed: Pre-deployed agent route not found"
    route_marker = 'E oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found'
    generic_error = "ERROR: health check failed"

    markers = extract_error_markers(
        "\n".join(
            [
                wrapper,
                generic_error,
                route_marker,
                wrapper,
            ]
        )
    )

    assert markers[0] == route_marker
    assert markers.count(wrapper) == 1
    assert generic_error in markers


def test_build_failure_evidence_populates_markers_and_signature():
    excerpt = "\n".join(
        [
            "ERROR: health check failed",
            "Traceback: deployment crashed",
        ]
    )

    evidence = build_failure_evidence(
        excerpt,
        source="github_job_log",
        run_id=123456789,
    )

    assert evidence is not None
    assert evidence.source == "github_job_log"
    assert evidence.run_id == 123456789
    assert set(evidence.markers) == {
        "ERROR: health check failed",
        "Traceback: deployment crashed",
    }
    assert evidence.signature is not None


def test_evidence_metadata_round_trip_preserves_fields():
    evidence = FailureEvidence(
        source="github_job_log",
        excerpt="ERROR: health check failed",
        markers=("ERROR: health check failed",),
        signature="sig-123",
        run_id=123456789,
    )

    metadata = evidence_to_metadata(evidence)
    round_tripped = evidence_from_metadata(metadata)

    assert round_tripped == evidence


def test_merge_and_resolve_failure_evidence_prefer_current_excerpt_and_keep_history():
    historical = FailureEvidence(
        source="github_job_log",
        excerpt="historical excerpt",
        markers=("historical marker",),
        signature="hist-123",
        run_id=111,
    )
    current = FailureEvidence(
        source="github_job_log",
        excerpt="current excerpt",
        markers=(),
        signature="curr-456",
        run_id=123456789,
    )

    merged = merge_failure_evidence(current, historical)

    assert merged is not None
    assert merged.excerpt == "current excerpt"
    assert merged.markers == historical.markers
    assert merged.signature == "curr-456"
    assert merged.run_id == 123456789


def test_build_summary_failure_evidence_uses_resolved_incident_metadata():
    incident_evidence = FailureEvidence(
        source="github_job_log",
        excerpt="historical excerpt",
        markers=(
            'E oc stderr: Error from server (NotFound): routes.route.openshift.io "langflow-simple-tool-calling-agent" not found',
        ),
        signature="hist-123",
        run_id=123456789,
    )
    incident = Incident(
        id=1,
        fingerprint="fp-abc123",
        workflow_name="QG4: Agent Deployment Integration Tests",
        workflow_file="agent-deployment-test.yaml",
        job_name="test-agent (langgraph-react-agent)",
        failed_step="Run integration test",
        branch="main",
        event="schedule",
        qg_label="QG4",
        metadata=evidence_to_metadata(incident_evidence),
    )
    failure = _sample_failure()

    resolved = resolve_failure_evidence(failure, incident)
    snapshots = build_summary_failure_evidence([failure], [incident])

    assert resolved is not None
    assert resolved.excerpt == "historical excerpt"
    assert snapshots["fp-abc123"]["primary_marker"] == incident_evidence.markers[0]
    assert snapshots["fp-abc123"]["evidence_signature"] == "hist-123"
