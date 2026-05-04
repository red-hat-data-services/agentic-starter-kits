"""Unit tests for evalhub_adapter config and evaluations modules.

Covers AgenticEvalParams.from_dict(), job_spec_to_task_config(),
get_benchmark(), resolve_scorers(), and load_queries().
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from evalhub_adapter.config import (
    AgenticEvalParams,
    _validate_url,
    job_spec_to_task_config,
)
from evalhub_adapter.evaluations import (
    ALL_SCORERS,
    BENCHMARKS,
    BenchmarkDef,
    QuerySpec,
    get_benchmark,
    load_queries,
    resolve_scorers,
)
from harness.runner import TaskConfig

pytestmark = pytest.mark.unit


class TestValidateUrl:
    """Tests for URL validation and security restrictions."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://evil.com/data",
            "javascript:alert(1)",
        ],
    )
    def test_rejects_non_http_schemes(self, url):
        """Non-HTTP(S) schemes are rejected."""
        with pytest.raises(ValueError, match="unsupported scheme"):
            _validate_url(url, "test_url")

    def test_rejects_empty_netloc(self):
        """URLs with no host component are rejected."""
        with pytest.raises(ValueError, match="no host"):
            _validate_url("http:", "test_url")

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8080/api",
            "http://127.0.0.1:5000",
            "http://[::1]:8080/api",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://0.0.0.0:8080",
        ],
    )
    def test_rejects_blocked_hosts(self, url):
        """Loopback, cloud metadata, and bind-all addresses are blocked."""
        with pytest.raises(ValueError, match="blocked host"):
            _validate_url(url, "test_url")

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8080/api",
            "http://127.0.0.1:5000",
            "http://[::1]:8080/api",
            "http://0.0.0.0:8080",
        ],
    )
    def test_allows_localhost_with_env_var(self, monkeypatch, caplog, url):
        """Localhost is allowed when EVALHUB_ALLOW_LOCALHOST=true."""
        monkeypatch.setenv("EVALHUB_ALLOW_LOCALHOST", "true")
        _validate_url(url, "test_url")
        assert "EVALHUB_ALLOW_LOCALHOST" in caplog.text

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
    )
    def test_rejects_cloud_metadata_even_with_localhost_allowed(self, monkeypatch, url):
        """Cloud metadata endpoints stay blocked even when localhost is allowed."""
        monkeypatch.setenv("EVALHUB_ALLOW_LOCALHOST", "true")
        with pytest.raises(ValueError, match="blocked host"):
            _validate_url(url, "test_url")

    def test_accepts_valid_https(self):
        """Valid HTTPS URLs pass without error."""
        _validate_url("https://agent.example.com:8080/chat", "test_url")

    def test_accepts_valid_http_with_warning(self, caplog):
        """Valid HTTP URLs pass but log a warning."""
        _validate_url("http://agent.internal:8080", "test_url")
        assert "unencrypted" in caplog.text.lower() or "HTTP" in caplog.text

    def test_accepts_cluster_internal_url(self):
        """Kubernetes cluster-internal URLs are allowed."""
        _validate_url("http://react-agent.namespace.svc.cluster.local:8080", "test_url")


class TestAgenticEvalParamsFromDict:
    """Tests for constructing AgenticEvalParams from a raw dict."""

    def test_from_dict_with_known_keys(self):
        """Known keys are set on the resulting dataclass."""
        raw = {
            "known_tools": ["search", "calculator"],
            "forbidden_actions": ["shell execution"],
            "max_latency_seconds": 5.0,
            "timeout_seconds": 60.0,
            "verify_ssl": True,
            "mlflow_tracking_uri": "http://mlflow:5000",
            "mlflow_experiment_name": "my-exp",
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.known_tools == ["search", "calculator"]
        assert params.forbidden_actions == ["shell execution"]
        assert params.max_latency_seconds == 5.0
        assert params.timeout_seconds == 60.0
        assert params.verify_ssl is True
        assert params.mlflow_tracking_uri == "http://mlflow:5000"
        assert params.mlflow_experiment_name == "my-exp"
        assert params.mlflow_trace_experiment_name == "my-exp"

    def test_from_dict_with_trace_experiment(self):
        """mlflow_trace_experiment_name can be set independently."""
        raw = {
            "mlflow_tracking_uri": "http://mlflow:5000",
            "mlflow_experiment_name": "eval-run-abc12",
            "mlflow_trace_experiment_name": "agent-traces",
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.mlflow_experiment_name == "eval-run-abc12"
        assert params.mlflow_trace_experiment_name == "agent-traces"

    def test_from_dict_ignores_unknown_keys(self):
        """Unknown keys in the dict are silently dropped."""
        raw = {
            "known_tools": ["web_search"],
            "totally_made_up": True,
            "another_unknown": 42,
            "mlflow_tracking_uri": "http://mlflow:5000",
            "mlflow_experiment_name": "test-exp",
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.known_tools == ["web_search"]
        assert not hasattr(params, "totally_made_up")
        assert not hasattr(params, "another_unknown")

    def test_from_dict_defaults(self):
        """An empty dict raises ValueError because MLflow fields are required."""
        with pytest.raises(ValueError, match="mlflow_tracking_uri"):
            AgenticEvalParams.from_dict({})

    def test_from_dict_defaults_with_mlflow(self):
        """Non-MLflow fields use defaults when only MLflow params are provided."""
        raw = {
            "mlflow_tracking_uri": "http://mlflow:5000",
            "mlflow_experiment_name": "test-exp",
        }
        params = AgenticEvalParams.from_dict(raw)

        assert params.known_tools == []
        assert params.forbidden_actions == []
        assert params.max_latency_seconds == 10.0
        assert params.timeout_seconds == 30.0
        assert params.verify_ssl is True
        assert params.stream is True

    def test_verify_ssl_false_without_env_raises(self, monkeypatch):
        """verify_ssl=False without EVALHUB_ALLOW_INSECURE_TLS raises ValueError."""
        monkeypatch.delenv("EVALHUB_ALLOW_INSECURE_TLS", raising=False)
        with pytest.raises(ValueError, match="EVALHUB_ALLOW_INSECURE_TLS"):
            AgenticEvalParams(
                verify_ssl=False,
                mlflow_tracking_uri="http://mlflow:5000",
                mlflow_experiment_name="test-exp",
            )

    def test_verify_ssl_false_with_env_true_succeeds(self, monkeypatch):
        """verify_ssl=False with EVALHUB_ALLOW_INSECURE_TLS=true is allowed."""
        monkeypatch.setenv("EVALHUB_ALLOW_INSECURE_TLS", "true")
        params = AgenticEvalParams(
            verify_ssl=False,
            mlflow_tracking_uri="http://mlflow:5000",
            mlflow_experiment_name="test-exp",
        )
        assert params.verify_ssl is False

    def test_from_dict_rejects_string_timeout(self):
        """String timeout_seconds raises TypeError."""
        with pytest.raises(TypeError, match="timeout_seconds.*numeric"):
            AgenticEvalParams.from_dict(
                {
                    "timeout_seconds": "not_a_number",
                    "mlflow_tracking_uri": "http://mlflow:5000",
                    "mlflow_experiment_name": "test-exp",
                }
            )

    def test_from_dict_rejects_path_traversal(self):
        """fixtures_path with '..' components is rejected."""
        with pytest.raises(ValueError, match=r"fixtures_path.*\.\."):
            AgenticEvalParams.from_dict(
                {
                    "fixtures_path": "../../etc",
                    "mlflow_tracking_uri": "http://mlflow:5000",
                    "mlflow_experiment_name": "test-exp",
                }
            )


class TestJobSpecToTaskConfig:
    """Tests for translating EvalHub job parameters into TaskConfig."""

    def test_job_spec_to_task_config(self):
        """All fields are mapped correctly into a TaskConfig."""
        params = AgenticEvalParams(
            timeout_seconds=45.0,
            mlflow_tracking_uri="http://mlflow:5000",
            mlflow_experiment_name="test-exp",
        )
        cfg = job_spec_to_task_config(
            agent_url="http://agent:8000",
            query="What is the weather?",
            expected_tools=["get_weather"],
            params=params,
            model_name="gpt-4o",
        )

        assert isinstance(cfg, TaskConfig)
        assert cfg.agent_url == "http://agent:8000"
        assert cfg.query == "What is the weather?"
        assert cfg.expected_tools == ["get_weather"]
        assert cfg.timeout_seconds == 45.0
        assert cfg.model == "gpt-4o"
        assert cfg.stream is True


EXPECTED_BENCHMARK_IDS = [
    "agentic-tool-use",
]


class TestGetBenchmark:
    """Tests for the BENCHMARKS registry and get_benchmark()."""

    @pytest.mark.parametrize("benchmark_id", EXPECTED_BENCHMARK_IDS)
    def test_get_benchmark_valid(self, benchmark_id: str):
        """Each registered benchmark ID returns a BenchmarkDef."""
        bm = get_benchmark(benchmark_id)
        assert isinstance(bm, BenchmarkDef)
        assert bm.queries_file, "queries_file must be a non-empty string"
        assert isinstance(bm.scorers, list)

    def test_get_benchmark_unknown_raises(self):
        """An unknown benchmark ID raises ValueError listing available IDs."""
        with pytest.raises(ValueError, match="no-such-benchmark") as exc_info:
            get_benchmark("no-such-benchmark")

        error_msg = str(exc_info.value)
        for bid in BENCHMARKS:
            assert bid in error_msg, (
                f"Error message should list available benchmark '{bid}'"
            )

    def test_expected_ids_match_registry(self):
        """EXPECTED_BENCHMARK_IDS stays in sync with BENCHMARKS registry."""
        assert set(EXPECTED_BENCHMARK_IDS) == set(BENCHMARKS.keys())


class TestResolveScorers:
    """Tests for resolve_scorers()."""

    def test_resolve_scorers_specific(self):
        """A benchmark with explicit scorers returns that exact list."""
        bm = get_benchmark("agentic-tool-use")
        scorers = resolve_scorers(bm)

        assert scorers == [
            "tool_selection",
            "tool_sequence",
            "hallucinated_tools",
            "tool_call_validity",
        ]

    def test_resolve_scorers_all(self):
        """The 'all' sentinel expands to ALL_SCORERS."""
        bm = BenchmarkDef(queries_file="unused.yaml", scorers=["all"])
        scorers = resolve_scorers(bm)
        assert scorers == list(ALL_SCORERS)

    def test_all_scorers_contains_expected(self):
        """ALL_SCORERS has exactly the 10 known scorer names."""
        expected = {
            "tool_selection",
            "tool_sequence",
            "hallucinated_tools",
            "tool_call_validity",
            "plan_coherence",
            "completeness",
            "latency",
            "pii_leakage",
            "policy_adherence",
            "injection_resistance",
        }
        assert set(ALL_SCORERS) == expected
        assert len(ALL_SCORERS) == len(set(ALL_SCORERS))

    def test_resolve_scorers_all_plus_custom(self):
        """The 'all' sentinel plus custom names returns ALL_SCORERS + the custom names."""
        bm = BenchmarkDef(
            queries_file="unused.yaml", scorers=["all", "my_custom_scorer"]
        )
        scorers = resolve_scorers(bm)
        assert scorers[: len(ALL_SCORERS)] == list(ALL_SCORERS)
        assert "my_custom_scorer" in scorers


class TestLoadQueries:
    """Tests for loading query files into QuerySpec lists."""

    def test_load_queries_valid_file(self, fixtures_dir: Path):
        """A well-formed YAML produces a list of QuerySpec objects."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "What is 2+2?"
                expected_tools: ["calculator"]
                expected_elements: ["4"]
              - query: "Search for cats"
                expected_tools: ["web_search"]
        """)
        (fixtures_dir / "test_queries.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="test_queries.yaml", scorers=["tool_selection"])

        queries = load_queries(bm, fixtures_dir)

        assert len(queries) == 2
        assert isinstance(queries[0], QuerySpec)
        assert queries[0].query == "What is 2+2?"
        assert queries[0].expected_tools == ["calculator"]
        assert queries[0].expected_elements == ["4"]
        assert queries[1].query == "Search for cats"

    def test_load_queries_missing_file(self, fixtures_dir: Path):
        """A non-existent queries file raises FileNotFoundError."""
        bm = BenchmarkDef(queries_file="does_not_exist.yaml", scorers=[])

        with pytest.raises(FileNotFoundError, match=r"does_not_exist\.yaml"):
            load_queries(bm, fixtures_dir)

    def test_load_queries_empty(self, fixtures_dir: Path):
        """An empty queries list raises ValueError."""
        yaml_content = textwrap.dedent("""\
            queries: []
        """)
        (fixtures_dir / "empty.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="empty.yaml", scorers=[])

        with pytest.raises(ValueError, match="non-empty"):
            load_queries(bm, fixtures_dir)

    def test_load_queries_defaults(self, fixtures_dir: Path):
        """Missing optional fields default to empty lists."""
        yaml_content = textwrap.dedent("""\
            queries:
              - query: "Hello world"
        """)
        (fixtures_dir / "defaults.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="defaults.yaml", scorers=[])

        queries = load_queries(bm, fixtures_dir)

        assert len(queries) == 1
        assert queries[0].query == "Hello world"
        assert queries[0].expected_tools == []
        assert queries[0].expected_elements == []

    def test_load_queries_null_value(self, fixtures_dir: Path):
        """queries: null (YAML None) raises ValueError."""
        (fixtures_dir / "null_queries.yaml").write_text("queries:\n")
        bm = BenchmarkDef(queries_file="null_queries.yaml", scorers=[])

        with pytest.raises(ValueError, match="non-empty"):
            load_queries(bm, fixtures_dir)

    def test_load_queries_missing_query_key(self, fixtures_dir: Path):
        """A query entry without 'query' raises ValueError."""
        yaml_content = textwrap.dedent("""\
            queries:
              - expected_tools: ["search"]
        """)
        (fixtures_dir / "bad_entry.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="bad_entry.yaml", scorers=[])

        with pytest.raises(ValueError, match="missing required 'query' field"):
            load_queries(bm, fixtures_dir)

    def test_load_queries_non_dict_top_level_raises(self, fixtures_dir: Path):
        """A YAML file with a list at top level raises ValueError."""
        yaml_content = textwrap.dedent("""\
            - query: "Hello"
        """)
        (fixtures_dir / "list_top.yaml").write_text(yaml_content)
        bm = BenchmarkDef(queries_file="list_top.yaml", scorers=[])

        with pytest.raises(ValueError, match="mapping"):
            load_queries(bm, fixtures_dir)
