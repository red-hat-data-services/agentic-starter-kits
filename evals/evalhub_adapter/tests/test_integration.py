"""Integration tests for the EvalHub adapter orchestration layer.

Tests the full _run_async pipeline and error paths using mocked HTTP
streaming responses (SSE). These do NOT require a live agent or EvalHub
instance.

Agents serve tool calls only via SSE streaming — their Pydantic
response_model strips the extra ``context`` field that would otherwise
carry tool-call history in non-streaming JSON.  The adapter therefore
uses ``stream=True`` by default so the harness runner can accumulate
``delta.tool_calls`` from the SSE event stream.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from evalhub_adapter.adapter import AgenticEvalAdapter

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_mlflow_network(monkeypatch):
    """Prevent real MLflow connections and allow insecure TLS in tests."""
    monkeypatch.setenv("EVALHUB_ALLOW_INSECURE_TLS", "true")
    with (
        patch("evalhub_adapter.adapter.MLflowTraceClient", None),
        patch("evalhub_adapter.adapter._log_mlflow_run", return_value=None),
    ):
        yield


_DUMMY_JOB_SPEC = {
    "id": "test-job-001",
    "provider_id": "agentic",
    "benchmark_id": "agentic-tool-use",
    "benchmark_index": 0,
    "model": {"name": "test-model", "url": "http://fake-agent:8080"},
    "parameters": {
        "known_tools": ["search"],
        "timeout_seconds": 5.0,
        "verify_ssl": False,
        "mlflow_tracking_uri": "http://mlflow:5000",
        "mlflow_experiment_name": "test-exp",
    },
    "callback_url": "http://localhost:8080",
    "tags": [],
}


def _write_job_spec(tmp_path: Path, overrides: dict | None = None) -> Path:
    """Write a JobSpec JSON file and return its path."""
    spec = {**_DUMMY_JOB_SPEC, **(overrides or {})}
    path = tmp_path / "job.json"
    path.write_text(json.dumps(spec))
    return path


def _make_adapter(job_spec_path: Path) -> AgenticEvalAdapter:
    """Create an adapter pointing at a specific job spec file."""
    return AgenticEvalAdapter(job_spec_path=str(job_spec_path))


def _make_job_spec(
    benchmark_id: str = "agentic-tool-use",
    agent_url: str = "http://fake-agent:8080",
    model_name: str = "test-model",
    parameters: dict | None = None,
    fixtures_path: str = "/tmp",
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
        "fixtures_path": fixtures_path,
        "mlflow_tracking_uri": "http://mlflow:5000",
        "mlflow_experiment_name": "test-exp",
    }
    if "fixtures_path" not in spec.parameters:
        spec.parameters["fixtures_path"] = fixtures_path
    return spec


def _make_callbacks() -> MagicMock:
    """Build a mock JobCallbacks that records calls."""
    cb = MagicMock()
    cb.report_status = MagicMock()
    cb.report_results = MagicMock()
    return cb


# ---------------------------------------------------------------------------
# SSE streaming mock infrastructure
# ---------------------------------------------------------------------------


def _sse_lines(tool_name: str | None = None) -> list[str]:
    """Build SSE data lines matching the agents' streaming endpoint format.

    Emits an optional tool-call chunk, then an assistant content chunk,
    then a final stop chunk with usage, then [DONE].
    """
    lines: list[str] = []
    if tool_name:
        lines.append(
            "data: "
            + json.dumps(
                {
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
        )
    lines.append(
        "data: "
        + json.dumps(
            {
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "Here are the results."},
                        "finish_reason": None,
                    }
                ],
            }
        )
    )
    lines.append(
        "data: "
        + json.dumps(
            {
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 42},
            }
        )
    )
    lines.append("data: [DONE]")
    return lines


class _MockSSEResponse:
    """Minimal stand-in for an httpx streaming response with SSE lines."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request(
                    "POST", "http://fake-agent:8080/chat/completions"
                ),
                response=httpx.Response(self.status_code),
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamCM:
    """Async context manager wrapping a ``_MockSSEResponse``."""

    def __init__(self, response: _MockSSEResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


def _stream_factory(lines: list[str]):
    """Return a callable suitable for ``mock_client.stream``'s *side_effect*.

    Each call produces a fresh ``_StreamCM`` / ``_MockSSEResponse`` pair so
    the async iterator is never exhausted across multiple queries.
    """

    def _side_effect(*_args, **_kwargs):
        return _StreamCM(_MockSSEResponse(list(lines)))

    return _side_effect


def _make_streaming_client(tool_name: str | None = None) -> AsyncMock:
    """Build a mock httpx.AsyncClient that serves SSE streaming responses."""
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(side_effect=_stream_factory(_sse_lines(tool_name)))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestRunAsyncHappyPath:
    """Verify the full orchestration loop with mocked SSE streaming responses."""

    @pytest.fixture()
    def adapter(self, tmp_path):
        return _make_adapter(_write_job_spec(tmp_path))

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

        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()
        mock_client = _make_streaming_client("search")

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
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

        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()
        mock_client = _make_streaming_client()

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
            results = adapter.run_benchmark_job(job_spec, callbacks)

        assert results.num_examples_evaluated == 1
        assert callbacks.report_results.call_count == 1

    def test_populates_mlflow_run_id_in_job_results(self, adapter, fixtures_dir: Path):
        """MLflow run_id is propagated to JobResults when logging succeeds."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec(
            fixtures_path=str(fixtures_dir),
            parameters={
                "known_tools": ["search"],
                "timeout_seconds": 5.0,
                "verify_ssl": False,
                "fixtures_path": str(fixtures_dir),
                "mlflow_tracking_uri": "https://mlflow.example.com",
                "mlflow_experiment_name": "agentic-evals",
            },
        )
        callbacks = _make_callbacks()
        mock_client = _make_streaming_client()

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
            with patch("evalhub_adapter.adapter.MLflowTraceClient", None):
                with patch(
                    "evalhub_adapter.adapter._log_mlflow_run", return_value="run-xyz"
                ):
                    results = asyncio.run(adapter._run_async(job_spec, callbacks))

        assert results.mlflow_run_id == "run-xyz"
        callbacks.report_results.assert_called_once()
        reported = callbacks.report_results.call_args.args[0]
        assert reported.mlflow_run_id == "run-xyz"


class TestAsyncioNestingGuard:
    """Verify the thread-pool fallback when called from an existing event loop."""

    def test_works_from_existing_event_loop(self, tmp_path, fixtures_dir: Path):
        """run_benchmark_job succeeds when called from inside an async context."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        adapter = _make_adapter(_write_job_spec(tmp_path))
        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()
        mock_client = _make_streaming_client()

        async def _call_from_async():
            with patch(
                "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
            ):
                return adapter.run_benchmark_job(job_spec, callbacks)

        results = asyncio.run(_call_from_async())
        assert results.num_examples_evaluated == 1


class TestErrorPaths:
    """Verify adapter error handling and failure reporting."""

    @pytest.fixture()
    def adapter(self, tmp_path):
        return _make_adapter(_write_job_spec(tmp_path))

    def test_unknown_benchmark_reports_failed(self, adapter, tmp_path):
        """An unknown benchmark_id reports FAILED status and raises ValueError."""
        job_spec = _make_job_spec(
            benchmark_id="nonexistent-benchmark", fixtures_path=str(tmp_path)
        )
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

        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(RuntimeError, match="All queries failed"):
                asyncio.run(adapter._run_async(job_spec, callbacks))

        assert callbacks.report_status.call_count >= 1

    def test_missing_fixture_yaml_raises(self, adapter, fixtures_dir: Path):
        """A benchmark pointing to a nonexistent YAML raises FileNotFoundError."""
        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()

        with pytest.raises(FileNotFoundError):
            asyncio.run(adapter._run_async(job_spec, callbacks))

    def test_malformed_agent_response_does_not_crash(self, adapter, fixtures_dir: Path):
        """An agent streaming valid JSON without choices[] is handled gracefully."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "test"
                expected_tools: ["search"]
              - query: "test2"
                expected_tools: []
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()

        malformed_lines = [
            'data: {"error": "internal server error"}',
            "data: [DONE]",
        ]
        mock_client = AsyncMock()
        mock_client.stream = MagicMock(side_effect=_stream_factory(malformed_lines))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
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

        job_spec = _make_job_spec(fixtures_path=str(fixtures_dir))
        callbacks = _make_callbacks()

        good_lines = _sse_lines("search")
        call_count = 0

        def _stream_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _StreamCM(_MockSSEResponse(list(good_lines)))
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(side_effect=_stream_side_effect)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
            results = asyncio.run(adapter._run_async(job_spec, callbacks))

        assert results.num_examples_evaluated == 2
        assert callbacks.report_results.call_count == 1
        assert 0.0 < results.overall_score <= 1.0


class TestMLflowTraceEnrichment:
    """Tests for MLflow trace enrichment during the evaluation pipeline."""

    @pytest.fixture()
    def adapter(self, tmp_path):
        return _make_adapter(_write_job_spec(tmp_path))

    def test_mlflow_trace_enrichment_called_per_query(
        self, adapter, fixtures_dir: Path
    ):
        """When MLflowTraceClient is available, enrich_eval_result is called per successful query."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello"
                expected_tools: []
              - query: "Search for cats"
                expected_tools: ["search"]
        """)
        (fixtures_dir / "tool_use.yaml").write_text(yaml_content)

        job_spec = _make_job_spec(
            fixtures_path=str(fixtures_dir),
            parameters={
                "known_tools": ["search"],
                "timeout_seconds": 5.0,
                "verify_ssl": False,
                "fixtures_path": str(fixtures_dir),
                "mlflow_tracking_uri": "https://mlflow.example.com",
                "mlflow_experiment_name": "test-exp",
                "mlflow_trace_experiment_name": "agent-traces",
            },
        )
        callbacks = _make_callbacks()
        mock_client = _make_streaming_client("search")

        mock_mlflow_client = MagicMock()
        mock_mlflow_client.verify_connection.return_value = True

        MockMLflowClass = MagicMock(return_value=mock_mlflow_client)

        with patch(
            "evalhub_adapter.adapter.httpx.AsyncClient", return_value=mock_client
        ):
            with patch("evalhub_adapter.adapter.MLflowTraceClient", MockMLflowClass):
                with patch(
                    "evalhub_adapter.adapter._log_mlflow_run", return_value=None
                ):
                    results = asyncio.run(adapter._run_async(job_spec, callbacks))

        assert results.num_examples_evaluated == 2
        assert mock_mlflow_client.enrich_eval_result.call_count == 2


class TestMain:
    """Tests for the CLI entry point."""

    @patch("evalhub_adapter.adapter.DefaultCallbacks")
    @patch("evalhub_adapter.adapter.AgenticEvalAdapter")
    @patch("evalhub_adapter.adapter.AdapterSettings")
    def test_main_calls_run_benchmark_job(
        self, mock_settings_cls, mock_adapter_cls, mock_callbacks_cls
    ):
        """main() wires AdapterSettings, constructs adapter, and runs the job."""
        from evalhub_adapter.adapter import main

        mock_settings = MagicMock()
        mock_settings_cls.from_env.return_value = mock_settings

        mock_adapter = MagicMock()
        mock_job_spec = MagicMock()
        mock_job_spec.id = "job-1"
        mock_job_spec.benchmark_id = "test"
        mock_job_spec.benchmark_index = 0
        mock_job_spec.provider_id = "prov-1"
        mock_job_spec.callback_url = "http://localhost:8080"
        mock_job_spec.model.name = "test-model"
        mock_job_spec.model.url = "http://agent:8000"
        mock_adapter.job_spec = mock_job_spec
        mock_adapter_cls.return_value = mock_adapter

        mock_results = MagicMock()
        mock_results.overall_score = 0.85
        mock_results.num_examples_evaluated = 5
        mock_results.duration_seconds = 3.0
        mock_adapter.run_benchmark_job.return_value = mock_results

        main()

        mock_settings_cls.from_env.assert_called_once()
        mock_adapter_cls.assert_called_once_with(settings=mock_settings)
        mock_adapter.run_benchmark_job.assert_called_once()

    @patch("evalhub_adapter.adapter.AdapterSettings")
    def test_main_exits_on_exception(self, mock_settings_cls):
        """main() catches exceptions and raises SystemExit(1)."""
        from evalhub_adapter.adapter import main

        mock_settings_cls.from_env.side_effect = RuntimeError("config error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
