"""Unit tests for the reporters module."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from rich.console import Console

from harness.reporters import (
    ReportData,
    Reporter,
    ScoreRecord,
    aggregate,
)
from harness.reporters.console import ConsoleReporter
from harness.reporters.json_file import JSONFileReporter
from harness.reporters.pytest_plugin import ScoreCollector
from harness.scorers import Score
from harness.scorers.latency import LatencyTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_score(
    name: str = "tool_selection",
    value: float = 1.0,
    passed: bool = True,
    details: dict | None = None,
) -> Score:
    return Score(name=name, value=value, passed=passed, details=details or {})


def _make_record(
    query: str = "What is the weather?",
    test_name: str = "test_weather",
    score: Score | None = None,
    agent: str = "react",
) -> ScoreRecord:
    return ScoreRecord(
        query=query,
        test_name=test_name,
        score=score or _make_score(),
        agent=agent,
        timestamp=1_000_000.0,
    )


# ---------------------------------------------------------------------------
# ScoreRecord
# ---------------------------------------------------------------------------


class TestScoreRecord:
    def test_creation_defaults(self) -> None:
        rec = ScoreRecord(query="hello", test_name="test_hi", score=_make_score())
        assert rec.agent == ""
        assert rec.timestamp > 0.0

    def test_creation_with_values(self) -> None:
        rec = _make_record(agent="crewai")
        assert rec.agent == "crewai"
        assert rec.query == "What is the weather?"


# ---------------------------------------------------------------------------
# aggregate()
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_empty_input(self) -> None:
        assert aggregate([]) == {}

    def test_single_metric(self) -> None:
        records = [
            _make_record(score=_make_score(value=0.8, passed=True)),
            _make_record(score=_make_score(value=0.6, passed=False)),
        ]
        result = aggregate(records)
        assert "tool_selection" in result
        ms = result["tool_selection"]
        assert ms.count == 2
        assert ms.mean == pytest.approx(0.7)
        assert ms.pass_rate == pytest.approx(0.5)
        assert ms.min_val == pytest.approx(0.6)
        assert ms.max_val == pytest.approx(0.8)

    def test_multiple_metrics(self) -> None:
        records = [
            _make_record(
                score=_make_score(name="tool_selection", value=1.0, passed=True)
            ),
            _make_record(score=_make_score(name="latency", value=0.9, passed=True)),
            _make_record(
                score=_make_score(name="tool_selection", value=0.5, passed=False)
            ),
        ]
        result = aggregate(records)
        assert len(result) == 2
        assert result["tool_selection"].count == 2
        assert result["latency"].count == 1

    def test_all_pass(self) -> None:
        records = [_make_record(score=_make_score(passed=True)) for _ in range(5)]
        result = aggregate(records)
        assert result["tool_selection"].pass_rate == pytest.approx(1.0)

    def test_all_fail(self) -> None:
        records = [_make_record(score=_make_score(passed=False)) for _ in range(3)]
        result = aggregate(records)
        assert result["tool_selection"].pass_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# JSONFileReporter
# ---------------------------------------------------------------------------


class TestJSONFileReporter:
    def test_writes_valid_json(self, tmp_path) -> None:
        records = [
            _make_record(),
            _make_record(score=_make_score(value=0.5, passed=False)),
        ]
        summary = aggregate(records)
        data = ReportData(records=records, summary=summary)

        path = tmp_path / "report.json"
        JSONFileReporter(path).report(data)

        payload = json.loads(path.read_text())
        assert payload["metadata"]["total_scores"] == 2
        assert "timestamp" in payload["metadata"]
        assert "tool_selection" in payload["summary"]
        assert len(payload["scores"]) == 2
        assert payload["latency_percentiles"] is None

    def test_empty_records(self, tmp_path) -> None:
        data = ReportData(records=[], summary={})
        path = tmp_path / "empty.json"
        JSONFileReporter(path).report(data)

        payload = json.loads(path.read_text())
        assert payload["metadata"]["total_scores"] == 0
        assert payload["scores"] == []
        assert payload["summary"] == {}

    def test_creates_parent_dirs(self, tmp_path) -> None:
        path = tmp_path / "nested" / "deep" / "report.json"
        data = ReportData(records=[], summary={})
        JSONFileReporter(path).report(data)
        assert path.exists()

    def test_latency_included(self, tmp_path) -> None:
        tracker = LatencyTracker()
        tracker.add(1.0)
        tracker.add(2.0)
        tracker.add(3.0)

        data = ReportData(records=[], summary={}, latency=tracker)
        path = tmp_path / "lat.json"
        JSONFileReporter(path).report(data)

        payload = json.loads(path.read_text())
        assert payload["latency_percentiles"] is not None
        assert "p50" in payload["latency_percentiles"]
        assert "p95" in payload["latency_percentiles"]
        assert payload["latency_percentiles"]["count"] == 3

    def test_latency_excluded_when_empty(self, tmp_path) -> None:
        tracker = LatencyTracker()
        data = ReportData(records=[], summary={}, latency=tracker)
        path = tmp_path / "no_lat.json"
        JSONFileReporter(path).report(data)

        payload = json.loads(path.read_text())
        assert payload["latency_percentiles"] is None

    def test_metadata_merged(self, tmp_path) -> None:
        data = ReportData(
            records=[],
            summary={},
            metadata={"run_id": "abc123", "agent": "react"},
        )
        path = tmp_path / "meta.json"
        JSONFileReporter(path).report(data)

        payload = json.loads(path.read_text())
        assert payload["metadata"]["run_id"] == "abc123"
        assert payload["metadata"]["agent"] == "react"
        assert "timestamp" in payload["metadata"]

    def test_score_details_preserved(self, tmp_path) -> None:
        score = _make_score(details={"expected": ["search"], "actual": ["search"]})
        records = [_make_record(score=score)]
        data = ReportData(records=records, summary=aggregate(records))
        path = tmp_path / "details.json"
        JSONFileReporter(path).report(data)

        payload = json.loads(path.read_text())
        assert payload["scores"][0]["details"]["expected"] == ["search"]


# ---------------------------------------------------------------------------
# ConsoleReporter
# ---------------------------------------------------------------------------


class TestConsoleReporter:
    def _capture(self, data: ReportData, verbose: bool = False) -> str:
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        reporter = ConsoleReporter(verbose=verbose)
        # Patch the internal console creation
        original_report = reporter.report

        def patched_report(d: ReportData) -> None:
            # Replace Console() inside the method with our capturing console
            import harness.reporters.console as mod

            orig_cls = mod.Console
            mod.Console = lambda **_kw: console  # type: ignore[assignment]
            try:
                original_report(d)
            finally:
                mod.Console = orig_cls  # type: ignore[assignment]

        patched_report(data)
        return buf.getvalue()

    def test_empty_data(self) -> None:
        output = self._capture(ReportData(records=[], summary={}))
        assert "No scores collected" in output

    def test_summary_table_present(self) -> None:
        records = [_make_record()]
        data = ReportData(records=records, summary=aggregate(records))
        output = self._capture(data)
        assert "Behavioral Test Summary" in output
        assert "tool_selection" in output

    def test_latency_table(self) -> None:
        tracker = LatencyTracker()
        tracker.add(1.5)
        tracker.add(2.5)

        records = [_make_record()]
        data = ReportData(records=records, summary=aggregate(records), latency=tracker)
        output = self._capture(data)
        assert "Latency Percentiles" in output

    def test_verbose_shows_details(self) -> None:
        records = [_make_record(query="What is the weather in NYC?")]
        data = ReportData(records=records, summary=aggregate(records))
        output = self._capture(data, verbose=True)
        assert "Score Details" in output
        assert "What is the weather in NYC?" in output

    def test_non_verbose_hides_details(self) -> None:
        records = [_make_record()]
        data = ReportData(records=records, summary=aggregate(records))
        output = self._capture(data, verbose=False)
        assert "Score Details" not in output


# ---------------------------------------------------------------------------
# ScoreCollector
# ---------------------------------------------------------------------------


class TestScoreCollector:
    def test_record_stores_entries(self) -> None:
        collector = ScoreCollector()
        collector.record("q1", _make_score(), test_name="t1")
        collector.record("q2", _make_score(), test_name="t2")
        assert len(collector.records) == 2
        assert collector.records[0].query == "q1"

    def test_latency_tracking(self) -> None:
        collector = ScoreCollector()
        lat_score = _make_score(
            name="latency", value=1.0, details={"latency_seconds": 2.5}
        )
        collector.record("q", lat_score, test_name="t")
        assert collector.latency.count == 1
        assert collector.latency.percentile(50) == pytest.approx(2.5)

    def test_non_latency_does_not_affect_tracker(self) -> None:
        collector = ScoreCollector()
        collector.record("q", _make_score(name="tool_selection"), test_name="t")
        assert collector.latency.count == 0

    def test_latency_without_details_key(self) -> None:
        collector = ScoreCollector()
        score = _make_score(name="latency", value=0.8, details={"max_seconds": 5})
        collector.record("q", score, test_name="t")
        assert collector.latency.count == 0

    def test_auto_populates_test_name(self) -> None:
        collector = ScoreCollector()
        collector.record("q", _make_score())
        assert collector.records[0].test_name == "test_auto_populates_test_name"

    def test_explicit_test_name_takes_precedence(self) -> None:
        collector = ScoreCollector()
        collector.record("q", _make_score(), test_name="explicit_name")
        assert collector.records[0].test_name == "explicit_name"

    def test_explicit_agent_takes_precedence(self) -> None:
        collector = ScoreCollector()
        collector.record("q", _make_score(), agent="my_agent")
        assert collector.records[0].agent == "my_agent"

    def test_agent_empty_when_no_pytestmark(self) -> None:
        collector = ScoreCollector()
        collector.record("q", _make_score())
        assert collector.records[0].agent == ""

    def test_records_returns_copy(self) -> None:
        collector = ScoreCollector()
        collector.record("q", _make_score(), test_name="t")
        records = collector.records
        records.clear()
        assert len(collector.records) == 1


# ---------------------------------------------------------------------------
# Reporter protocol
# ---------------------------------------------------------------------------


class TestReporterProtocol:
    def test_json_reporter_is_reporter(self) -> None:
        assert isinstance(JSONFileReporter("/tmp/test.json"), Reporter)

    def test_console_reporter_is_reporter(self) -> None:
        assert isinstance(ConsoleReporter(), Reporter)


# ---------------------------------------------------------------------------
# Integration: collector -> aggregate -> reporters pipeline
# ---------------------------------------------------------------------------


class TestIntegrationPipeline:
    def test_full_pipeline(self, tmp_path) -> None:
        collector = ScoreCollector()
        collector.record(
            "What is 2+2?",
            _make_score(name="answer_quality", value=1.0, passed=True),
            test_name="test_math",
            agent="autogen",
        )
        collector.record(
            "Tell me a joke",
            _make_score(name="answer_quality", value=0.7, passed=True),
            test_name="test_joke",
            agent="autogen",
        )
        collector.record(
            "What is 2+2?",
            _make_score(
                name="latency",
                value=0.9,
                passed=True,
                details={"latency_seconds": 1.2},
            ),
            test_name="test_math",
            agent="autogen",
        )

        records = collector.records
        summary = aggregate(records)
        latency = collector.latency if collector.latency.count > 0 else None

        data = ReportData(records=records, summary=summary, latency=latency)

        # JSON report
        json_path = tmp_path / "pipeline.json"
        JSONFileReporter(json_path).report(data)
        payload = json.loads(json_path.read_text())

        assert payload["metadata"]["total_scores"] == 3
        assert "answer_quality" in payload["summary"]
        assert "latency" in payload["summary"]
        assert payload["latency_percentiles"] is not None
        assert payload["summary"]["answer_quality"]["count"] == 2
        assert payload["summary"]["answer_quality"]["mean"] == pytest.approx(0.85)

        # Console report (just verify no exceptions)
        ConsoleReporter(verbose=True).report(data)
