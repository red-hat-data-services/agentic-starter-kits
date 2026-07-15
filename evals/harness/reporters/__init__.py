"""Score reporting — shared types and aggregation utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from harness.scorers import Score
from harness.scorers.latency import LatencyTracker


@dataclass
class ScoreRecord:
    """A single scored result tied to a query and test."""

    query: str
    test_name: str
    score: Score
    agent: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class MetricSummary:
    """Aggregated statistics for one metric across all records."""

    name: str
    mean: float
    pass_rate: float
    count: int
    min_val: float
    max_val: float


@dataclass
class ReportData:
    """Complete dataset handed to a Reporter."""

    records: list[ScoreRecord]
    summary: dict[str, MetricSummary]
    latency: LatencyTracker | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Reporter(Protocol):
    """Minimal interface every reporter must satisfy."""

    def report(self, data: ReportData) -> None: ...


def aggregate(records: list[ScoreRecord]) -> dict[str, MetricSummary]:
    """Group ScoreRecords by score.name and compute per-metric stats."""
    if not records:
        return {}

    groups: dict[str, list[Score]] = {}
    for rec in records:
        groups.setdefault(rec.score.name, []).append(rec.score)

    result: dict[str, MetricSummary] = {}
    for name, scores in groups.items():
        values = [s.value for s in scores]
        count = len(values)
        result[name] = MetricSummary(
            name=name,
            mean=sum(values) / count,
            pass_rate=sum(1 for s in scores if s.passed) / count,
            count=count,
            min_val=min(values),
            max_val=max(values),
        )

    return result


__all__ = [
    "ScoreRecord",
    "MetricSummary",
    "ReportData",
    "Reporter",
    "aggregate",
    "ConsoleReporter",
    "JSONFileReporter",
]


def __getattr__(name: str) -> Any:
    if name == "ConsoleReporter":
        from harness.reporters.console import ConsoleReporter

        return ConsoleReporter
    if name == "JSONFileReporter":
        from harness.reporters.json_file import JSONFileReporter

        return JSONFileReporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
