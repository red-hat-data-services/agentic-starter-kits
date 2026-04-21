"""Scorers for latency thresholds and percentile tracking."""

from __future__ import annotations

import math

from harness.runner import TaskResult
from harness.scorers import Score


def score_latency(result: TaskResult, max_seconds: float) -> Score:
    """Pass/fail check on response latency against a threshold."""
    if max_seconds <= 0:
        return Score(
            name="latency",
            value=0.0,
            passed=False,
            details={
                "latency_seconds": result.latency_seconds,
                "max_seconds": max_seconds,
                "reason": "invalid threshold (max_seconds <= 0)",
            },
        )
    ratio = result.latency_seconds / max_seconds
    passed = result.latency_seconds <= max_seconds

    return Score(
        name="latency",
        value=1.0 if passed else min(1.0, max(0.0, 1.0 - (ratio - 1.0))),
        passed=passed,
        details={
            "latency_seconds": result.latency_seconds,
            "max_seconds": max_seconds,
            "utilization": ratio,
        },
    )


class LatencyTracker:
    """Accumulates latency measurements and computes percentiles.

    Usage:
        tracker = LatencyTracker()
        tracker.add(result1.latency_seconds)
        tracker.add(result2.latency_seconds)
        p95 = tracker.percentile(95)
    """

    def __init__(self) -> None:
        self._values: list[float] = []

    def add(self, latency_seconds: float) -> None:
        """Record a latency measurement."""
        self._values.append(latency_seconds)

    def percentile(self, p: float) -> float | None:
        """Compute the p-th percentile (0-100) of recorded latencies.

        Uses the nearest-rank method. Returns None if no values recorded.
        """
        if not self._values:
            return None
        sorted_vals = sorted(self._values)
        rank = math.ceil(p / 100 * len(sorted_vals))
        idx = max(0, min(rank - 1, len(sorted_vals) - 1))
        return sorted_vals[idx]

    @property
    def count(self) -> int:
        """Number of recorded measurements."""
        return len(self._values)

    def summary(self) -> dict[str, float | int | None]:
        """Return a dict with p50, p95, p99, min, max, and count."""
        return {
            "count": self.count,
            "p50": self.percentile(50),
            "p95": self.percentile(95),
            "p99": self.percentile(99),
            "min": min(self._values) if self._values else None,
            "max": max(self._values) if self._values else None,
        }
