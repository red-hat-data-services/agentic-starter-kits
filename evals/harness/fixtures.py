"""Golden-query loader for behavioral tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_golden(
    fixtures_dir: Path | str,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Load golden queries from *fixtures_dir*/golden_queries.yaml.

    Expected YAML shape: ``{"queries": [{"category": str, "query": str, ...}]}``
    """
    path = Path(fixtures_dir) / "golden_queries.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    queries = data.get("queries", [])
    if category:
        queries = [q for q in queries if q.get("category") == category]
    return queries
