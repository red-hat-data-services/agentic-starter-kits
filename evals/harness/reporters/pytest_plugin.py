"""Pytest plugin — collect scores during a test run and emit reports."""

from __future__ import annotations

import inspect
import threading
import time
import warnings

import pytest

from harness.reporters import ReportData, ScoreRecord, aggregate
from harness.scorers import Score
from harness.scorers.latency import LatencyTracker

_CATEGORY_MARKERS = frozenset(
    {
        "adversarial",
        "model_baseline",
        "api_contract",
        "slow",
        "unit",
        "integration",
    }
)

_SKIP_MARKERS = _CATEGORY_MARKERS | frozenset(
    {
        "parametrize",
        "usefixtures",
        "filterwarnings",
        "skip",
        "skipif",
        "xfail",
    }
)


class ScoreCollector:
    """Accumulates ScoreRecords throughout a pytest session."""

    def __init__(self) -> None:
        self._records: list[ScoreRecord] = []
        self._latency = LatencyTracker()
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Clear all accumulated state."""
        with self._lock:
            self._records.clear()
            self._latency = LatencyTracker()

    @staticmethod
    def _infer_from_request(request: pytest.FixtureRequest) -> tuple[str, str]:
        """Return (test_name, agent) using the pytest request fixture."""
        test_name = request.node.name
        agent = ""
        for marker in request.node.iter_markers():
            if marker.name not in _SKIP_MARKERS:
                agent = marker.name
                break
        return (test_name, agent)

    @staticmethod
    def _infer_from_caller() -> tuple[str, str]:
        """Return (test_name, agent) by walking the stack for a test_* frame.

        Prefer ``_infer_from_request`` when a pytest ``request`` fixture is
        available — it is faster, deterministic, and avoids the reference-cycle
        hazard of ``inspect.currentframe()``.
        """
        frame = inspect.currentframe()
        if not frame:
            return ("", "")

        try:
            caller = frame.f_back
            test_name = ""
            test_globals: dict | None = None

            while caller is not None:
                name = caller.f_code.co_name
                if name.startswith("test_"):
                    test_name = name
                    test_globals = caller.f_globals
                    break
                caller = caller.f_back

            if not test_name or test_globals is None:
                return ("", "")

            agent = ""
            pytestmark = test_globals.get("pytestmark")
            if pytestmark is not None:
                marks = pytestmark if isinstance(pytestmark, list) else [pytestmark]
                for mark in marks:
                    mark_name = getattr(mark, "name", None) or getattr(
                        getattr(mark, "mark", None), "name", None
                    )
                    if mark_name and mark_name not in _SKIP_MARKERS:
                        agent = mark_name
                        break

            return (test_name, agent)
        finally:
            del frame, caller

    def record(
        self,
        query: str,
        score: Score,
        *,
        test_name: str = "",
        agent: str = "",
        request: pytest.FixtureRequest | None = None,
    ) -> None:
        """Store a score and track latency when applicable.

        When *test_name* or *agent* are not provided they are inferred
        automatically.  Pass *request* (the pytest ``request`` fixture) for
        fast, deterministic attribution via ``request.node``.  When *request*
        is ``None``, falls back to stack-frame walking.
        """
        if not test_name or not agent:
            if request is not None:
                inferred_test, inferred_agent = self._infer_from_request(request)
            else:
                inferred_test, inferred_agent = self._infer_from_caller()
            if not test_name:
                test_name = inferred_test
            if not agent:
                agent = inferred_agent

        record = ScoreRecord(
            query=query,
            test_name=test_name,
            score=score,
            agent=agent,
            timestamp=time.time(),
        )

        with self._lock:
            self._records.append(record)
            if score.name == "latency" and "latency_seconds" in score.details:
                self._latency.add(score.details["latency_seconds"])
            elif score.name == "latency" and "latency_seconds" not in score.details:
                warnings.warn(
                    f"Score '{score.name}' is named 'latency' but details "
                    f"is missing 'latency_seconds' key; latency percentiles "
                    f"will not track this score",
                    stacklevel=2,
                )

    @property
    def records(self) -> list[ScoreRecord]:
        with self._lock:
            return list(self._records)

    @property
    def latency(self) -> LatencyTracker:
        with self._lock:
            return self._latency


# Module-level singleton so the session-finish hook can access the same
# instance that the fixture hands to individual tests.
_collector = ScoreCollector()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("reporters", "Score reporting")
    group.addoption(
        "--report-json",
        metavar="PATH",
        help="Write JSON score report to PATH",
    )
    group.addoption(
        "--report-console",
        action="store_true",
        default=False,
        help="Print Rich summary tables",
    )
    group.addoption(
        "--report-verbose",
        action="store_true",
        default=False,
        help="Include per-score breakdown in console report",
    )


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    """Reset the collector at the start of each session."""
    _collector.reset()


@pytest.fixture(scope="session")
def score_collector() -> ScoreCollector:
    """Session-wide score collector shared across all tests."""
    return _collector


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Emit reports after all tests have finished."""
    config = session.config
    json_path = config.getoption("--report-json", default=None)
    console = config.getoption("--report-console", default=False)
    verbose = config.getoption("--report-verbose", default=False)

    if not json_path and not console:
        return

    records = _collector.records
    summary = aggregate(records)
    latency = _collector.latency if _collector.latency.count > 0 else None
    data = ReportData(records=records, summary=summary, latency=latency)

    if json_path:
        try:
            from harness.reporters.json_file import JSONFileReporter

            JSONFileReporter(json_path).report(data)
        except Exception as exc:
            warnings.warn(f"JSON reporter failed: {exc}", stacklevel=1)
    if console:
        try:
            from harness.reporters.console import ConsoleReporter

            ConsoleReporter(verbose=verbose).report(data)
        except Exception as exc:
            warnings.warn(f"Console reporter failed: {exc}", stacklevel=1)


__all__ = ["ScoreCollector", "score_collector"]
