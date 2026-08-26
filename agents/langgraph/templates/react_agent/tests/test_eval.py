"""Tests for evaluation/run_eval.py — config loading, data loading, scorer resolution."""

from __future__ import annotations

import pytest

pytest.importorskip(
    "mlflow", reason="eval dependencies not installed (install with --extra eval)"
)

import sys  # noqa: E402
import textwrap  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import yaml  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "evaluation"
sys.path.insert(0, str(EVAL_DIR.parent))

from evaluation.run_eval import (  # noqa: E402
    attach_expectations,
    get_scorers,
    load_eval_config,
    load_eval_data,
    resolve_scorer,
)

# ---------------------------------------------------------------------------
# load_eval_config
# ---------------------------------------------------------------------------


class TestLoadEvalConfig:
    def test_loads_default_config(self) -> None:
        config = load_eval_config()
        assert "scorers" in config
        assert "core" in config["scorers"]
        assert "guidelines" in config["scorers"]

    def test_loads_from_custom_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            yaml.dump({"scorers": {"core": [], "use_case": [], "guidelines": []}})
        )
        config = load_eval_config(str(custom))
        assert config["scorers"]["core"] == []

    def test_core_scorers_have_name_and_module(self) -> None:
        config = load_eval_config()
        for entry in config["scorers"]["core"]:
            assert "name" in entry, f"Missing 'name' in core scorer: {entry}"
            assert "module" in entry, f"Missing 'module' in core scorer: {entry}"


# ---------------------------------------------------------------------------
# load_eval_data
# ---------------------------------------------------------------------------


class TestLoadEvalData:
    def test_returns_empty_list_when_queries_is_none(self, tmp_path: Path) -> None:
        """Regression: YAML `queries:` with no items parses as None, not []."""
        data_file = tmp_path / "eval_data.yaml"
        data_file.write_text("queries:\n")
        result = load_eval_data(str(data_file))
        assert result == []

    def test_returns_empty_list_when_key_missing(self, tmp_path: Path) -> None:
        data_file = tmp_path / "eval_data.yaml"
        data_file.write_text("other_key: value\n")
        result = load_eval_data(str(data_file))
        assert result == []

    def test_returns_queries_list(self, tmp_path: Path) -> None:
        data_file = tmp_path / "eval_data.yaml"
        data_file.write_text(
            textwrap.dedent("""\
                queries:
                  - inputs:
                      question: "What is 2+2?"
                    expectations:
                      expected_facts:
                        - "4"
            """)
        )
        result = load_eval_data(str(data_file))
        assert len(result) == 1
        assert result[0]["inputs"]["question"] == "What is 2+2?"

    def test_loads_default_placeholder_data(self) -> None:
        result = load_eval_data()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# resolve_scorer
# ---------------------------------------------------------------------------


class TestResolveScorer:
    def test_skips_scorer_when_env_flag_not_set(self) -> None:
        entry = {
            "name": "PIILeakage",
            "module": "mlflow.genai.scorers.deepeval",
            "enabled_by_env": "EVAL_ENABLE_PII",
        }
        with patch.dict("os.environ", {}, clear=True):
            result = resolve_scorer(entry, "openai:/gpt-4o-mini")
        assert result is None

    def test_loads_scorer_when_env_flag_is_true(self) -> None:
        captured = {}

        class FakePIILeakage:
            def __init__(self, model):
                captured["model"] = model

        mock_module = MagicMock()
        mock_module.PIILeakage = FakePIILeakage

        entry = {
            "name": "PIILeakage",
            "module": "mlflow.genai.scorers.deepeval",
            "enabled_by_env": "EVAL_ENABLE_PII",
        }
        with (
            patch.dict("os.environ", {"EVAL_ENABLE_PII": "true"}, clear=True),
            patch("importlib.import_module", return_value=mock_module),
        ):
            result = resolve_scorer(entry, "openai:/gpt-4o-mini")
        assert isinstance(result, FakePIILeakage)
        assert captured["model"] == "openai:/gpt-4o-mini"

    def test_uses_model_env_override(self) -> None:
        captured = {}

        class FakePIILeakage:
            def __init__(self, model):
                captured["model"] = model

        mock_module = MagicMock()
        mock_module.PIILeakage = FakePIILeakage

        entry = {
            "name": "PIILeakage",
            "module": "mlflow.genai.scorers.deepeval",
            "enabled_by_env": "EVAL_ENABLE_PII",
            "model_env": "EVAL_PII_MODEL",
        }
        with (
            patch.dict(
                "os.environ",
                {"EVAL_ENABLE_PII": "true", "EVAL_PII_MODEL": "openai:/gpt-4.1-mini"},
                clear=True,
            ),
            patch("importlib.import_module", return_value=mock_module),
        ):
            resolve_scorer(entry, "openai:/gpt-4o-mini")
        assert captured["model"] == "openai:/gpt-4.1-mini"

    def test_custom_scorer_function_not_called_with_model(self) -> None:
        """Regression: @scorer decorated functions don't accept model= argument."""

        def my_custom_scorer():
            pass

        mock_module = MagicMock()
        mock_module.my_custom_scorer = my_custom_scorer

        entry = {"name": "my_custom_scorer", "module": "scorers"}
        with patch("importlib.import_module", return_value=mock_module):
            result = resolve_scorer(entry, "openai:/gpt-4o-mini")
        assert result is my_custom_scorer

    def test_class_scorer_instantiated_with_model(self) -> None:
        mock_class = type("MockScorer", (), {"__init__": lambda self, model: None})
        mock_module = MagicMock()
        mock_module.Safety = mock_class

        entry = {"name": "Safety", "module": "mlflow.genai.scorers"}
        with patch("importlib.import_module", return_value=mock_module):
            result = resolve_scorer(entry, "openai:/gpt-4o-mini")
        assert isinstance(result, mock_class)


# ---------------------------------------------------------------------------
# get_scorers
# ---------------------------------------------------------------------------


class TestGetScorers:
    def test_includes_guidelines_scorer(self) -> None:
        config = {
            "scorers": {
                "core": [],
                "use_case": [],
                "guidelines": ["Be helpful", "Be safe"],
            }
        }
        scorers = get_scorers(config, "openai:/gpt-4o-mini")
        assert len(scorers) == 1
        assert scorers[0].name == "domain_guidelines"

    def test_empty_guidelines_skips_scorer(self) -> None:
        config = {"scorers": {"core": [], "use_case": [], "guidelines": []}}
        scorers = get_scorers(config, "openai:/gpt-4o-mini")
        assert len(scorers) == 0

    def test_none_use_case_handled(self) -> None:
        config = {"scorers": {"core": [], "use_case": None, "guidelines": []}}
        scorers = get_scorers(config, "openai:/gpt-4o-mini")
        assert scorers == []

    def test_missing_scorers_key_handled(self) -> None:
        """Regression: empty YAML returns {}, bracket access to 'scorers' crashes."""
        config = {}
        scorers = get_scorers(config, "openai:/gpt-4o-mini")
        assert scorers == []


# ---------------------------------------------------------------------------
# attach_expectations
# ---------------------------------------------------------------------------


def _make_trace(trace_id: str, timestamp_ms: int) -> MagicMock:
    """Create a mock trace with the given ID and timestamp."""
    trace = MagicMock()
    trace.info.trace_id = trace_id
    trace.info.timestamp_ms = timestamp_ms
    return trace


class TestAttachExpectations:
    def test_matches_by_index_order(self) -> None:
        """Traces sorted by timestamp are matched to eval_data by index."""
        traces = [
            _make_trace("t1", 1000),
            _make_trace("t2", 2000),
            _make_trace("t3", 3000),
        ]
        eval_data = [
            {"inputs": {"question": "Q1"}, "expectations": {"expected_facts": ["A1"]}},
            {"inputs": {"question": "Q2"}, "expectations": {"expected_facts": ["A2"]}},
            {"inputs": {"question": "Q3"}, "expectations": {"expected_facts": ["A3"]}},
        ]
        with patch("evaluation.run_eval.mlflow") as mock_mlflow:
            matched_ids = attach_expectations(traces, eval_data)

        assert matched_ids == {"t1", "t2", "t3"}
        assert mock_mlflow.log_expectation.call_count == 3

    def test_sorts_traces_by_timestamp(self) -> None:
        """Even if traces arrive out of order, they get sorted before matching."""
        traces = [
            _make_trace("t3", 3000),
            _make_trace("t1", 1000),
            _make_trace("t2", 2000),
        ]
        eval_data = [
            {"inputs": {"question": "Q1"}, "expectations": {"expected_facts": ["A1"]}},
            {"inputs": {"question": "Q2"}, "expectations": {"expected_facts": ["A2"]}},
        ]
        with patch("evaluation.run_eval.mlflow") as mock_mlflow:
            matched_ids = attach_expectations(traces, eval_data)

        assert matched_ids == {"t1", "t2"}
        calls = mock_mlflow.log_expectation.call_args_list
        assert calls[0].kwargs["trace_id"] == "t1"
        assert calls[1].kwargs["trace_id"] == "t2"

    def test_more_queries_than_traces(self) -> None:
        """If fewer traces than queries, only match what we have."""
        traces = [_make_trace("t1", 1000)]
        eval_data = [
            {"inputs": {"question": "Q1"}, "expectations": {"expected_facts": ["A1"]}},
            {"inputs": {"question": "Q2"}, "expectations": {"expected_facts": ["A2"]}},
        ]
        with patch("evaluation.run_eval.mlflow"):
            matched_ids = attach_expectations(traces, eval_data)

        assert matched_ids == {"t1"}

    def test_query_without_expectations(self) -> None:
        """Queries with no expectations still match (trace ID tracked)."""
        traces = [_make_trace("t1", 1000)]
        eval_data = [{"inputs": {"question": "Q1"}}]

        with patch("evaluation.run_eval.mlflow") as mock_mlflow:
            matched_ids = attach_expectations(traces, eval_data)

        assert matched_ids == {"t1"}
        mock_mlflow.log_expectation.assert_not_called()
