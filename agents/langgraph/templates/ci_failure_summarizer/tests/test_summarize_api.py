"""Tests for summarize API contract and /summarize route behavior."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ci_failure_summarizer.models import FailureRecord, Incident, SummaryResult
from main import SummarizeRequest, SummarizeResponse


class TestSummarizeModels:
    def test_summarize_request_defaults(self):
        req = SummarizeRequest()
        assert req.run_id is None
        assert req.post_to_slack is True

    def test_summarize_response_shape(self):
        resp = SummarizeResponse(
            run_id=1,
            run_url="https://example.test/run/1",
            workflow_name="QG4: Agent Deployment Integration Tests",
            failures=[],
            summary_text="no failures",
            slack_posted=False,
        )
        assert resp.logs_available is False


def _summary_result() -> SummaryResult:
    failure = FailureRecord(
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
        fingerprint="fp-abc123",
        logs_available=False,
        metadata={"failure_area": "health-check"},
    )
    incident = Incident(
        id=1,
        fingerprint=failure.fingerprint,
        workflow_name=failure.workflow_name,
        workflow_file=failure.workflow_file,
        job_name=failure.job_name,
        failed_step=failure.failed_step,
        branch=failure.branch,
        event=failure.event,
        qg_label=failure.qg_label,
        occurrence_count=2,
    )
    return SummaryResult(
        run_id=123456789,
        run_url="https://github.com/example/actions/runs/123456789",
        workflow_name="QG4: Agent Deployment Integration Tests",
        failures=[failure],
        incidents=[incident],
        summary_text="*CI Triage Summary* — metadata-only triage",
        slack_posted=False,
        slack_skipped_reason="SLACK_WEBHOOK_URL is not configured",
        logs_available=False,
    )


@pytest.fixture
def summarize_client():
    mock_saver = MagicMock()
    mock_store = MagicMock()
    mock_closure = MagicMock(return_value=MagicMock())

    @contextmanager
    def fake_saver_ctx(*_args, **_kwargs):
        yield mock_saver

    env = {
        "BASE_URL": "http://localhost:8080/v1",
        "MODEL_ID": "test-model",
        "API_KEY": "test-key",
        "GITHUB_REPOSITORY": "red-hat-data-services/agentic-starter-kits",
        "GITHUB_WORKFLOW": "QG4: Agent Deployment Integration Tests",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "agent_memory",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "test",
    }

    with (
        patch("main.enable_tracing"),
        patch("main.get_database_uri", return_value="postgresql://test"),
        patch("main.PostgresSaver.from_conn_string", side_effect=fake_saver_ctx),
        patch("main.IncidentStore", return_value=mock_store),
        patch("main.get_graph_closure", return_value=mock_closure),
        patch.dict(os.environ, env, clear=False),
    ):
        import main

        with TestClient(main.app) as client:
            yield client


class TestSummarizeRoute:
    def test_summarize_returns_grouped_failures(self, summarize_client):
        with patch(
            "main.SummarizerOrchestrator.run",
            return_value=_summary_result(),
        ) as mock_run:
            response = summarize_client.post(
                "/summarize",
                json={"post_to_slack": False},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["run_id"] == 123456789
        assert body["workflow_name"] == "QG4: Agent Deployment Integration Tests"
        assert len(body["failures"]) == 1
        assert body["failures"][0]["job_name"] == "test-agent (langgraph-react-agent)"
        assert body["failures"][0]["occurrence_count"] == 2
        assert body["logs_available"] is False
        assert body["slack_posted"] is False
        mock_run.assert_called_once_with(run_id=None)

    def test_summarize_accepts_run_id(self, summarize_client):
        with patch(
            "main.SummarizerOrchestrator.run",
            return_value=_summary_result(),
        ) as mock_run:
            response = summarize_client.post(
                "/summarize",
                json={"run_id": 999, "post_to_slack": False},
            )

        assert response.status_code == 200
        mock_run.assert_called_once_with(run_id=999)

    def test_summarize_maps_value_error_to_400(self, summarize_client):
        with patch(
            "main.SummarizerOrchestrator.run",
            side_effect=ValueError("GITHUB_REPOSITORY is required"),
        ):
            response = summarize_client.post("/summarize", json={})

        assert response.status_code == 400
        assert "GITHUB_REPOSITORY" in response.json()["detail"]

    def test_summarize_maps_runtime_error_to_502(self, summarize_client):
        with patch(
            "main.SummarizerOrchestrator.run",
            side_effect=RuntimeError("No workflow runs found"),
        ):
            response = summarize_client.post("/summarize", json={})

        assert response.status_code == 502
        assert "No workflow runs found" in response.json()["detail"]

    def test_summarize_maps_run_mismatch_to_400(self, summarize_client):
        with patch(
            "main.SummarizerOrchestrator.run",
            side_effect=ValueError("Run 999 is not from workflow"),
        ):
            response = summarize_client.post(
                "/summarize",
                json={"run_id": 999, "post_to_slack": False},
            )

        assert response.status_code == 400
        assert "Run 999 is not from workflow" in response.json()["detail"]

    def test_images_route_rejects_path_traversal(self, summarize_client, tmp_path):
        import main

        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (tmp_path / "secret.txt").write_text("secret")

        with patch.object(main, "_IMAGES_DIR", images_dir):
            response = summarize_client.get("/images/../secret.txt")

        assert response.status_code == 404
