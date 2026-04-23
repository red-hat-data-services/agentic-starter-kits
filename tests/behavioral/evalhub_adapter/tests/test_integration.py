"""Integration tests for the EvalHub adapter orchestration layer.

Tests the full _run_async pipeline and error paths using mocked HTTP
responses. These do NOT require a live agent or EvalHub instance.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

from evalhub_adapter.adapter import AgenticEvalAdapter, _report, _report_fatal
from evalhub_adapter.benchmarks import QuerySpec

pytestmark = pytest.mark.integration


def _make_job_spec(
    benchmark_id: str = "agentic-tool-use",
    agent_url: str = "http://fake-agent:8080",
    model_name: str = "test-model",
    parameters: dict | None = None,
) -> MagicMock:
    """Build a mock JobSpec with the fields the adapter reads."""
    spec = MagicMock()
    spec.id = "test-job-001"
    spec.benchmark_id = benchmark_id
    spec.benchmark_index = 0
    spec.model.name = model_name
    spec.model.url = agent_url
    spec.parameters = parameters or {
        "known_tools": ["search"],
        "timeout_seconds": 5.0,
        "verify_ssl": False,
    }
    return spec


def _make_callbacks() -> MagicMock:
    """Build a mock JobCallbacks that records calls."""
    cb = MagicMock()
    cb.report_status = MagicMock()
    cb.report_results = MagicMock()
    return cb


def _agent_response(tool_name: str | None = None) -> dict:
    """Build a minimal OpenAI-compatible chat completion response."""
    message: dict = {"role": "assistant", "content": "Here are the results."}
    if tool_name:
        message["tool_calls"] = [
            {
                "type": "function",
                "function": {"name": tool_name, "arguments": "{}"},
            }
        ]
    return {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"total_tokens": 42},
    }


class TestRunAsyncHappyPath:
    """Verify the full orchestration loop with mocked HTTP responses."""

    @pytest.fixture()
    def adapter(self):
        return AgenticEvalAdapter()

    def test_full_pipeline_completes_all_phases(self, adapter, fixtures_dir: Path):
        """_run_async reports all 5 phases and returns populated JobResults."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "What is the weather?"
                expected_tools: ["search"]
              - query: "Hello there"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        mock_response = httpx.Response(
            200,
            json=_agent_response("search"),
            request=httpx.Request("POST", "http://fake-agent:8080/chat/completions"),
        )

        with patch("harness.runner.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client):
                results = asyncio.run(adapter._run_async(job_spec, callbacks))

        assert callbacks.report_status.call_count >= 5
        assert callbacks.report_results.call_count == 1

        assert results.overall_score > 0
        assert results.num_examples_evaluated == 2
        assert results.duration_seconds > 0
        assert results.benchmark_id == "agentic-tool-use"
        assert results.model_name == "test-model"

    def test_run_benchmark_job_sync_wrapper(self, adapter, fixtures_dir: Path):
        """run_benchmark_job (sync) delegates to _run_async correctly."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        mock_response = httpx.Response(
            200,
            json=_agent_response(),
            request=httpx.Request("POST", "http://fake-agent:8080/chat/completions"),
        )

        with patch("evalhub_adapter.adapter.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = adapter.run_benchmark_job(job_spec, callbacks)

        assert results.num_examples_evaluated == 1
        assert callbacks.report_results.call_count == 1


class TestAsyncioNestingGuard:
    """Verify the thread-pool fallback when called from an existing event loop."""

    def test_works_from_existing_event_loop(self, fixtures_dir: Path):
        """run_benchmark_job succeeds when called from inside an async context."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        adapter = AgenticEvalAdapter()
        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        mock_response = httpx.Response(
            200,
            json=_agent_response(),
            request=httpx.Request("POST", "http://fake-agent:8080/chat/completions"),
        )

        async def _call_from_async():
            with patch("evalhub_adapter.adapter.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                return adapter.run_benchmark_job(job_spec, callbacks)

        results = asyncio.run(_call_from_async())
        assert results.num_examples_evaluated == 1


class TestErrorPaths:
    """Verify adapter error handling and failure reporting."""

    @pytest.fixture()
    def adapter(self):
        return AgenticEvalAdapter()

    def test_unknown_benchmark_reports_failed(self, adapter):
        """An unknown benchmark_id reports FAILED status and raises ValueError."""
        job_spec = _make_job_spec(benchmark_id="nonexistent-benchmark")
        callbacks = _make_callbacks()

        with pytest.raises(ValueError, match="nonexistent-benchmark"):
            asyncio.run(adapter._run_async(job_spec, callbacks))

        assert callbacks.report_status.call_count >= 1

    def test_unreachable_agent_all_queries_fail(self, adapter, fixtures_dir: Path):
        """When all queries fail (unreachable agent), adapter raises RuntimeError."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "test query"
                expected_tools: ["search"]
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        with patch("evalhub_adapter.adapter.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="All queries failed"):
                asyncio.run(adapter._run_async(job_spec, callbacks))

        assert callbacks.report_status.call_count >= 1

    def test_missing_fixture_yaml_raises(self, adapter, fixtures_dir: Path):
        """A benchmark pointing to a nonexistent YAML raises FileNotFoundError."""
        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        with pytest.raises(FileNotFoundError):
            asyncio.run(adapter._run_async(job_spec, callbacks))

    def test_malformed_agent_response_does_not_crash(self, adapter, fixtures_dir: Path):
        """An agent returning valid JSON without choices[] is handled gracefully."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "test"
                expected_tools: ["search"]
              - query: "test2"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        malformed_response = httpx.Response(
            200,
            json={"error": "internal server error"},
            request=httpx.Request("POST", "http://fake-agent:8080/chat/completions"),
        )

        with patch("evalhub_adapter.adapter.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=malformed_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = asyncio.run(adapter._run_async(job_spec, callbacks))

        assert results.num_examples_evaluated == 2
        assert callbacks.report_results.call_count == 1

    def test_partial_failure_still_produces_results(self, adapter, fixtures_dir: Path):
        """When some queries fail and some succeed, results are still reported."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "good query"
                expected_tools: ["search"]
              - query: "bad query"
                expected_tools: ["search"]
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec()
        callbacks = _make_callbacks()

        good_response = httpx.Response(
            200,
            json=_agent_response("search"),
            request=httpx.Request("POST", "http://fake-agent:8080/chat/completions"),
        )

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return good_response
            raise httpx.ConnectError("Connection refused")

        with patch("evalhub_adapter.adapter.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=_side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = asyncio.run(adapter._run_async(job_spec, callbacks))

        assert results.num_examples_evaluated == 2
        assert callbacks.report_results.call_count == 1
        assert results.overall_score is not None


class TestReportHelpers:
    """Verify the status reporting helper functions."""

    def test_report_sends_running_status(self):
        from evalhub.adapter import JobPhase, JobStatus

        callbacks = _make_callbacks()
        _report(callbacks, JobStatus.RUNNING, JobPhase.INITIALIZING, 0.0, "Starting")
        callbacks.report_status.assert_called_once()

    def test_report_fatal_sends_failed_status(self):
        from evalhub.adapter import JobPhase

        callbacks = _make_callbacks()
        _report_fatal(callbacks, "Something broke", JobPhase.RUNNING_EVALUATION)
        callbacks.report_status.assert_called_once()
