"""JSON file reporter — writes structured score data to disk."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.reporters import ReportData


def _safe_float(v: float) -> float | None:
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _sanitize_json_value(v: Any) -> Any:
    if isinstance(v, float):
        return _safe_float(v)
    if isinstance(v, dict):
        return {k: _sanitize_json_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_sanitize_json_value(item) for item in v]
    return v


class JSONFileReporter:
    """Writes a JSON score report to a file."""

    def __init__(self, output_path: str | Path) -> None:
        self._path = Path(output_path)

    def report(self, data: ReportData) -> None:
        """Serialize *data* to JSON and write to the configured path."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        metadata: dict[str, Any] = {}
        metadata.update(data.metadata)
        metadata["timestamp"] = datetime.now(timezone.utc).isoformat()
        metadata["total_scores"] = len(data.records)

        summary: dict[str, dict[str, float | int | None]] = {}
        for name, ms in data.summary.items():
            summary[name] = {
                "mean": _safe_float(ms.mean),
                "pass_rate": _safe_float(ms.pass_rate),
                "count": ms.count,
                "min": _safe_float(ms.min_val),
                "max": _safe_float(ms.max_val),
            }

        latency_percentiles: dict[str, float | int | None] | None = None
        if data.latency is not None and data.latency.count > 0:
            latency_percentiles = _sanitize_json_value(data.latency.summary())

        scores: list[dict[str, Any]] = []
        for rec in data.records:
            scores.append(
                {
                    "query": rec.query,
                    "test_name": rec.test_name,
                    "score_name": rec.score.name,
                    "value": _safe_float(rec.score.value),
                    "passed": rec.score.passed,
                    "details": _sanitize_json_value(rec.score.details),
                }
            )

        payload: dict[str, Any] = {
            "metadata": metadata,
            "summary": summary,
            "latency_percentiles": latency_percentiles,
            "scores": scores,
        }

        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, allow_nan=False)


__all__ = ["JSONFileReporter"]
