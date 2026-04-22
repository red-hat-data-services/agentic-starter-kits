"""Fixtures for Vanilla Python OpenAI Responses agent evals."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Coroutine

import httpx
import pytest
import yaml

from harness.runner import TaskResult, TaskConfig, run_task

try:
    from harness.mlflow_client import MLflowTraceClient
except ImportError:
    MLflowTraceClient = None  # type: ignore[misc,assignment]


@pytest.fixture
def agent_url() -> str:
    """Vanilla Python agent URL from VANILLA_PYTHON_AGENT_URL env var or default localhost:8003."""
    return os.environ.get("VANILLA_PYTHON_AGENT_URL", "http://localhost:8003")


@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async httpx client that is closed after the test."""
    async with httpx.AsyncClient() as client:
        yield client


def _find_repo_root() -> Path:
    """Walk up from this file to find the repository root."""
    path = Path(__file__).resolve().parent
    while path.parent != path:
        if (path / "tests" / "behavioral" / "configs" / "thresholds.yaml").is_file():
            return path
        path = path.parent
    pytest.skip("Could not find repo root (no tests/behavioral/configs/thresholds.yaml)")


@pytest.fixture
def eval_config() -> dict[str, Any]:
    """Load threshold configuration from the shared configs directory."""
    config_path = _find_repo_root() / "tests" / "behavioral" / "configs" / "thresholds.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


PRICE_EVIDENCE = ["price", "cost", "$", "dollar"]
REVIEW_EVIDENCE = ["review", "rating", "star", "recommend"]


def load_golden(category: str | None = None) -> list[dict[str, Any]]:
    """Load golden queries from the fixtures directory, optionally filtering by category."""
    path = Path(__file__).parent / "fixtures" / "golden_queries.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    queries = data.get("queries", [])
    if category:
        queries = [q for q in queries if q.get("category") == category]
    return queries


@pytest.fixture
def known_tools() -> list[str]:
    """Tools available on the Vanilla Python OpenAI Responses agent."""
    return ["search_price", "search_reviews"]


@pytest.fixture
def vanilla_python_thresholds(eval_config: dict[str, Any]) -> dict[str, Any]:
    """Load the vanilla_python section from the shared thresholds config."""
    return eval_config["vanilla_python"]


@pytest.fixture
def run_eval(
    agent_url: str, http_client: httpx.AsyncClient
) -> Callable[..., Coroutine[Any, Any, TaskResult]]:
    """Run eval with automatic MLflow enrichment when available.

    Overrides the root run_eval fixture to add MLflow trace data
    (tool calls, token usage) after each request.
    """
    mlflow = None
    if MLflowTraceClient is not None:
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        experiment = os.environ.get("MLFLOW_EXPERIMENT_NAME")
        if tracking_uri and experiment:
            mlflow = MLflowTraceClient(tracking_uri, experiment)

    async def _run(
        query: str,
        expected_tools: list[str] | None = None,
        timeout_seconds: float = 30.0,
        max_tokens_budget: int | None = None,
        model: str | None = None,
        stream: bool = False,
    ) -> TaskResult:
        config = TaskConfig(
            agent_url=agent_url,
            query=query,
            expected_tools=expected_tools,
            timeout_seconds=timeout_seconds,
            max_tokens_budget=max_tokens_budget,
            model=model,
            stream=stream,
        )
        request_start_ms = int(time.time() * 1000)
        result = await run_task(config, client=http_client)

        if mlflow is not None and result.success:
            try:
                mlflow.enrich_eval_result(result, since_ms=request_start_ms)
            except Exception:
                logging.getLogger(__name__).debug(
                    "MLflow enrichment failed — continuing without trace data",
                    exc_info=True,
                )

        return result

    return _run
