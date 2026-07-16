"""PostgreSQL-backed incident and summary history store."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from ci_failure_summarizer.models import FailureRecord, Incident

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ci_incidents (
    id SERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    workflow_name TEXT NOT NULL,
    workflow_file TEXT,
    job_name TEXT NOT NULL,
    failed_step TEXT,
    branch TEXT,
    event TEXT,
    qg_label TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    latest_run_id BIGINT,
    latest_run_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ci_summary_history (
    id SERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    summary_text TEXT NOT NULL,
    slack_posted BOOLEAN NOT NULL DEFAULT FALSE,
    logs_available BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    incident_fingerprints TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""


class IncidentStore:
    """Dedicated incident persistence separate from LangGraph checkpoints."""

    def __init__(self, db_uri: str) -> None:
        self.db_uri = db_uri

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.db_uri, row_factory=dict_row) as conn:
            yield conn

    def setup(self) -> None:
        with self._connection() as conn:
            conn.execute(SCHEMA_SQL)
            conn.commit()

    def upsert_failures(self, failures: list[FailureRecord]) -> list[Incident]:
        if not failures:
            return []

        now = datetime.now(UTC)
        incidents: list[Incident] = []

        with self._connection() as conn:
            for failure in failures:
                row = conn.execute(
                    """
                    INSERT INTO ci_incidents (
                        fingerprint, workflow_name, workflow_file, job_name,
                        failed_step, branch, event, qg_label,
                        first_seen_at, last_seen_at, occurrence_count,
                        latest_run_id, latest_run_url, metadata
                    ) VALUES (
                        %(fingerprint)s, %(workflow_name)s, %(workflow_file)s, %(job_name)s,
                        %(failed_step)s, %(branch)s, %(event)s, %(qg_label)s,
                        %(now)s, %(now)s, 1,
                        %(run_id)s, %(run_url)s, %(metadata)s::jsonb
                    )
                    ON CONFLICT (fingerprint) DO UPDATE SET
                        workflow_name = EXCLUDED.workflow_name,
                        workflow_file = EXCLUDED.workflow_file,
                        job_name = EXCLUDED.job_name,
                        failed_step = EXCLUDED.failed_step,
                        branch = EXCLUDED.branch,
                        event = EXCLUDED.event,
                        qg_label = EXCLUDED.qg_label,
                        last_seen_at = CASE
                            WHEN ci_incidents.latest_run_id IS DISTINCT FROM EXCLUDED.latest_run_id
                            THEN EXCLUDED.last_seen_at
                            ELSE ci_incidents.last_seen_at
                        END,
                        occurrence_count = CASE
                            WHEN ci_incidents.latest_run_id IS DISTINCT FROM EXCLUDED.latest_run_id
                            THEN ci_incidents.occurrence_count + 1
                            ELSE ci_incidents.occurrence_count
                        END,
                        latest_run_id = EXCLUDED.latest_run_id,
                        latest_run_url = EXCLUDED.latest_run_url,
                        metadata = ci_incidents.metadata || EXCLUDED.metadata
                    RETURNING *
                    """,
                    {
                        "fingerprint": failure.fingerprint,
                        "workflow_name": failure.workflow_name,
                        "workflow_file": failure.workflow_file,
                        "job_name": failure.job_name,
                        "failed_step": failure.failed_step,
                        "branch": failure.branch,
                        "event": failure.event,
                        "qg_label": failure.qg_label,
                        "now": now,
                        "run_id": failure.run_id,
                        "run_url": failure.run_url,
                        "metadata": json.dumps(failure.metadata),
                    },
                ).fetchone()
                incidents.append(self._row_to_incident(row))
            conn.commit()

        return incidents

    def record_summary(
        self,
        *,
        run_id: int,
        summary_text: str,
        slack_posted: bool,
        logs_available: bool,
        incident_fingerprints: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self._connection() as conn:
            row = conn.execute(
                """
                INSERT INTO ci_summary_history (
                    run_id, summary_text, slack_posted, logs_available,
                    incident_fingerprints, metadata
                ) VALUES (
                    %(run_id)s, %(summary_text)s, %(slack_posted)s, %(logs_available)s,
                    %(fingerprints)s, %(metadata)s::jsonb
                )
                RETURNING id
                """,
                {
                    "run_id": run_id,
                    "summary_text": summary_text,
                    "slack_posted": slack_posted,
                    "logs_available": logs_available,
                    "fingerprints": incident_fingerprints,
                    "metadata": json.dumps(metadata or {}),
                },
            ).fetchone()
            conn.commit()
            return int(row["id"])

    def get_incident(self, fingerprint: str) -> Incident | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ci_incidents WHERE fingerprint = %s",
                (fingerprint,),
            ).fetchone()
        return self._row_to_incident(row) if row else None

    @staticmethod
    def _row_to_incident(row: dict[str, Any]) -> Incident:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Incident(
            id=row["id"],
            fingerprint=row["fingerprint"],
            workflow_name=row["workflow_name"],
            workflow_file=row.get("workflow_file"),
            job_name=row["job_name"],
            failed_step=row.get("failed_step"),
            branch=row.get("branch"),
            event=row.get("event"),
            qg_label=row.get("qg_label"),
            first_seen_at=row["first_seen_at"].isoformat()
            if row.get("first_seen_at")
            else None,
            last_seen_at=row["last_seen_at"].isoformat()
            if row.get("last_seen_at")
            else None,
            occurrence_count=int(row.get("occurrence_count") or 1),
            latest_run_id=row.get("latest_run_id"),
            latest_run_url=row.get("latest_run_url"),
            metadata=metadata,
        )
