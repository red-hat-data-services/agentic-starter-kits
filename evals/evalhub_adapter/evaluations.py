"""Benchmark registry and golden query loader for EvalHub."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class QuerySpec:
    """A single golden query with expected outcomes."""

    query: str
    expected_tools: list[str] = field(default_factory=list)
    expected_elements: list[str] = field(default_factory=list)


@dataclass
class BenchmarkDef:
    """Definition of a benchmark: which queries to run and which scorers to apply."""

    queries_file: str
    scorers: list[str]


# Registry of available evaluations. Currently ships agentic-tool-use only;
# additional suites (coherence, safety, latency) will be added as query
# files are populated.
BENCHMARKS: dict[str, BenchmarkDef] = {
    "agentic-tool-use": BenchmarkDef(
        queries_file="tool_use.yaml",
        scorers=[
            "tool_selection",
            "tool_sequence",
            "hallucinated_tools",
            "tool_call_validity",
        ],
    ),
}

# Canonical list of every scorer that _run_scorer can dispatch.
# Used by resolve_scorers() when a benchmark specifies "all".
# No current benchmark uses "all"; each benchmark lists its scorers
# explicitly.  Kept as infrastructure so future benchmarks can opt
# into the full suite without enumerating every scorer name.
ALL_SCORERS = [
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
]


def get_benchmark(benchmark_id: str) -> BenchmarkDef:
    """Look up a benchmark by ID. Raises ValueError if unknown."""
    if benchmark_id not in BENCHMARKS:
        available = ", ".join(sorted(BENCHMARKS.keys()))
        raise ValueError(f"Unknown benchmark '{benchmark_id}'. Available: {available}")
    return BENCHMARKS[benchmark_id]


def resolve_scorers(benchmark: BenchmarkDef) -> list[str]:
    """Expand 'all' to the full scorer list."""
    if "all" in benchmark.scorers:
        extras = [s for s in benchmark.scorers if s != "all" and s not in ALL_SCORERS]
        if extras:
            logger.warning(
                "Scorers %s listed alongside 'all' will be appended to ALL_SCORERS",
                extras,
            )
        return list(ALL_SCORERS) + extras
    return list(benchmark.scorers)


def load_queries(benchmark: BenchmarkDef, fixtures_dir: Path) -> list[QuerySpec]:
    """Load golden queries from the benchmark's YAML file."""
    path = fixtures_dir / benchmark.queries_file
    if not path.exists():
        raise FileNotFoundError(f"Benchmark queries file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping at top level, got {type(data).__name__} in {path}"
        )

    raw_queries = data.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError(f"Expected non-empty 'queries' list in {path}")

    queries: list[QuerySpec] = []
    for i, entry in enumerate(raw_queries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Query entry {i} must be a mapping, got {type(entry).__name__} in {path}"
            )
        if "query" not in entry:
            raise ValueError(
                f"Query entry {i} missing required 'query' field in {path}"
            )
        if not isinstance(entry["query"], str):
            raise ValueError(
                f"Query entry {i} field 'query' must be a string in {path}"
            )

        expected_tools = entry.get("expected_tools", [])
        if not isinstance(expected_tools, list) or not all(
            isinstance(tool, str) for tool in expected_tools
        ):
            raise ValueError(
                f"Query entry {i} field 'expected_tools' must be a list[str] in {path}"
            )

        expected_elements = entry.get("expected_elements", [])
        if not isinstance(expected_elements, list) or not all(
            isinstance(elem, str) for elem in expected_elements
        ):
            raise ValueError(
                f"Query entry {i} field 'expected_elements' must be a list[str] in {path}"
            )

        queries.append(
            QuerySpec(
                query=entry["query"],
                expected_tools=expected_tools,
                expected_elements=expected_elements,
            )
        )
    return queries
