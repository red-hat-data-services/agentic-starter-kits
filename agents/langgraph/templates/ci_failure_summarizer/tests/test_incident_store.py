"""Tests for incident persistence behavior (mocked PostgreSQL)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from ci_failure_summarizer.incident_store import IncidentStore
from ci_failure_summarizer.models import FailureEvidence, FailureRecord


def _sample_failure(*, fingerprint: str = "fp-abc123") -> FailureRecord:
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
        failed_step="Health check",
        qg_label="QG4",
        fingerprint=fingerprint,
        logs_available=False,
        metadata={"failure_area": "health-check", "log_status_code": 403},
    )


def test_row_to_incident_parses_metadata_json_string():
    now = datetime(2026, 7, 15, 2, 30, tzinfo=UTC)
    row = {
        "id": 7,
        "fingerprint": "fp-abc123",
        "workflow_name": "QG4: Agent Deployment Integration Tests",
        "workflow_file": "agent-deployment-test.yaml",
        "job_name": "test-agent (langgraph-react-agent)",
        "failed_step": "Health check",
        "branch": "main",
        "event": "schedule",
        "qg_label": "QG4",
        "first_seen_at": now,
        "last_seen_at": now,
        "occurrence_count": 3,
        "latest_run_id": 123456789,
        "latest_run_url": "https://github.com/example/actions/runs/123456789",
        "metadata": '{"failure_area": "health-check"}',
    }

    incident = IncidentStore._row_to_incident(row)

    assert incident.id == 7
    assert incident.fingerprint == "fp-abc123"
    assert incident.occurrence_count == 3
    assert incident.metadata["failure_area"] == "health-check"


def test_upsert_failures_returns_empty_for_no_input():
    store = IncidentStore("postgresql://test")

    assert store.upsert_failures([]) == []


def test_upsert_failures_commits_inserted_row():
    store = IncidentStore("postgresql://test")
    now = datetime(2026, 7, 15, 2, 30, tzinfo=UTC)
    row = {
        "id": 1,
        "fingerprint": "fp-abc123",
        "workflow_name": "QG4: Agent Deployment Integration Tests",
        "workflow_file": "agent-deployment-test.yaml",
        "job_name": "test-agent (langgraph-react-agent)",
        "failed_step": "Health check",
        "branch": "main",
        "event": "schedule",
        "qg_label": "QG4",
        "first_seen_at": now,
        "last_seen_at": now,
        "occurrence_count": 1,
        "latest_run_id": 123456789,
        "latest_run_url": "https://github.com/example/actions/runs/123456789",
        "metadata": {"failure_area": "health-check"},
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = row

    @contextmanager
    def fake_connection():
        yield mock_conn

    with patch.object(store, "_connection", fake_connection):
        incidents = store.upsert_failures([_sample_failure()])

    assert len(incidents) == 1
    assert incidents[0].fingerprint == "fp-abc123"
    mock_conn.commit.assert_called_once()


def test_record_summary_returns_inserted_id():
    store = IncidentStore("postgresql://test")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"id": 42}

    @contextmanager
    def fake_connection():
        yield mock_conn

    with patch.object(store, "_connection", fake_connection):
        summary_id = store.record_summary(
            run_id=123456789,
            summary_text="*CI Triage Summary* — test",
            slack_posted=False,
            logs_available=False,
            incident_fingerprints=["fp-abc123"],
            metadata={"slack_skipped_reason": "SLACK_WEBHOOK_URL is not configured"},
        )

    assert summary_id == 42
    mock_conn.commit.assert_called_once()
    execute_kwargs = mock_conn.execute.call_args.args[1]
    assert execute_kwargs["run_id"] == 123456789
    assert execute_kwargs["fingerprints"] == ["fp-abc123"]


def test_upsert_failures_skips_occurrence_increment_for_same_run_id():
    store = IncidentStore("postgresql://test")
    now = datetime(2026, 7, 15, 2, 30, tzinfo=UTC)
    row = {
        "id": 1,
        "fingerprint": "fp-abc123",
        "workflow_name": "QG4: Agent Deployment Integration Tests",
        "workflow_file": "agent-deployment-test.yaml",
        "job_name": "test-agent (langgraph-react-agent)",
        "failed_step": "Health check",
        "branch": "main",
        "event": "schedule",
        "qg_label": "QG4",
        "first_seen_at": now,
        "last_seen_at": now,
        "occurrence_count": 2,
        "latest_run_id": 123456789,
        "latest_run_url": "https://github.com/example/actions/runs/123456789",
        "metadata": {"failure_area": "health-check"},
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = row

    @contextmanager
    def fake_connection():
        yield mock_conn

    with patch.object(store, "_connection", fake_connection):
        incidents = store.upsert_failures([_sample_failure()])

    sql = mock_conn.execute.call_args.args[0]
    assert "latest_run_id IS DISTINCT FROM EXCLUDED.latest_run_id" in sql
    assert len(incidents) == 1
    assert incidents[0].occurrence_count == 2


def test_upsert_failures_persists_typed_failure_evidence():
    store = IncidentStore("postgresql://test")
    now = datetime(2026, 7, 15, 2, 30, tzinfo=UTC)
    row = {
        "id": 1,
        "fingerprint": "fp-abc123",
        "workflow_name": "QG4: Agent Deployment Integration Tests",
        "workflow_file": "agent-deployment-test.yaml",
        "job_name": "test-agent (langgraph-react-agent)",
        "failed_step": "Health check",
        "branch": "main",
        "event": "schedule",
        "qg_label": "QG4",
        "first_seen_at": now,
        "last_seen_at": now,
        "occurrence_count": 1,
        "latest_run_id": 123456789,
        "latest_run_url": "https://github.com/example/actions/runs/123456789",
        "metadata": {"failure_area": "health-check"},
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = row

    @contextmanager
    def fake_connection():
        yield mock_conn

    failure = _sample_failure()
    failure = FailureRecord(
        **{
            **failure.__dict__,
            "evidence": FailureEvidence(
                source="github_job_log",
                excerpt="ERROR: health check failed",
                markers=("ERROR: health check failed",),
                signature="sig-123",
                run_id=123456789,
            ),
        }
    )

    with patch.object(store, "_connection", fake_connection):
        store.upsert_failures([failure])

    execute_kwargs = mock_conn.execute.call_args.args[1]
    assert (
        '"evidence_excerpt": "ERROR: health check failed"' in execute_kwargs["metadata"]
    )
    assert '"evidence_signature": "sig-123"' in execute_kwargs["metadata"]
