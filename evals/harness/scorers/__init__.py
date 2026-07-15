"""Scorers for evaluating agent responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Score:
    """Result of a single scoring function."""

    name: str
    value: float  # 0.0 to 1.0
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


__all__ = ["Score"]
