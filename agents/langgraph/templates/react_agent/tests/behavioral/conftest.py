"""Fixtures for LangGraph React agent evals."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import warnings
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Coroutine

import httpx
import pytest
import yaml
from harness.fixtures import load_golden as _load_golden_from
from harness.runner import TaskConfig, TaskResult, run_task

try:
    from harness.mlflow_client import MLflowTraceClient
except ImportError:
    MLflowTraceClient = None  # type: ignore[misc,assignment]


def _find_repo_root() -> Path:
    """Walk up from this file to find the repository root.

    Uses the presence of tests/behavioral/configs/thresholds.yaml as
    the sentinel to distinguish the repo root from agent-level directories
    that also contain pyproject.toml and tests/behavioral/.
    """
    path = Path(__file__).resolve().parent
    while path.parent != path:
        candidate = path / "tests" / "behavioral" / "configs" / "thresholds.yaml"
        if candidate.is_file():
            return path
        path = path.parent
    raise FileNotFoundError(
        "Could not find repo root (no tests/behavioral/configs/thresholds.yaml)"
    )


FIXTURES_DIR = Path(__file__).parent / "fixtures"
STREAM = False


def load_golden(category: str | None = None) -> list[dict[str, Any]]:
    """Load golden queries from the fixtures directory, optionally filtering by category."""
    return _load_golden_from(FIXTURES_DIR, category)


@pytest.fixture
def agent_url() -> str:
    """React agent URL from REACT_AGENT_URL env var or default localhost:8000."""
    return os.environ.get("REACT_AGENT_URL", "http://localhost:8000")


@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async httpx client that is closed after the test."""
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def eval_config() -> dict[str, Any]:
    """Load threshold configuration from the shared configs directory."""
    config_path = (
        _find_repo_root() / "tests" / "behavioral" / "configs" / "thresholds.yaml"
    )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def known_tools() -> list[str]:
    """Tools available on the LangGraph React agent."""
    return ["search"]


@pytest.fixture
def react_thresholds(eval_config: dict[str, Any]) -> dict[str, Any]:
    """Load the langgraph_react section from the shared thresholds config."""
    return eval_config["langgraph_react"]


@pytest.fixture
def run_eval(
    agent_url: str, http_client: httpx.AsyncClient
) -> Callable[..., Coroutine[Any, Any, TaskResult]]:
    """Run eval with automatic MLflow enrichment when available.

    Overrides the root run_eval fixture to add MLflow trace data
    (tool calls, token usage) after each request.

    NOTE: MLFLOW_EXPERIMENT_NAME isolation — all agents read this from the
    same env var.  If multiple agents (react_agent, human_in_the_loop,
    agentic_rag) share the same experiment name during a CI run, MLflow
    enrichment may pull tool spans from sibling agents (e.g. ``create_file``
    from HITL or ``retriever`` from agentic_rag), causing spurious
    hallucinated-tool failures.  The ``since_ms`` timestamp filter mitigates
    this for sequential runs, but concurrent execution is not safe.  Each
    agent deployment should set a unique MLFLOW_EXPERIMENT_NAME to avoid
    cross-contamination.
    """
    mlflow = None
    if MLflowTraceClient is not None:
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        experiment = os.environ.get("MLFLOW_EXPERIMENT_NAME")
        if tracking_uri and experiment:
            mlflow = MLflowTraceClient(tracking_uri, experiment)

    _start_times: dict[int, int] = {}

    async def _run(
        query: str,
        expected_tools: list[str] | None = None,
        timeout_seconds: float = 30.0,
        max_tokens_budget: int | None = None,
        model: str | None = None,
        enrich: bool = True,
    ) -> TaskResult:
        config = TaskConfig(
            agent_url=agent_url,
            query=query,
            expected_tools=expected_tools,
            timeout_seconds=timeout_seconds,
            max_tokens_budget=max_tokens_budget,
            model=model,
            stream=STREAM,
        )
        request_start_ms = int(time.time() * 1000)
        result = await run_task(config, client=http_client)
        _start_times[id(result)] = request_start_ms

        if enrich and mlflow is not None and result.success:
            try:
                await asyncio.to_thread(
                    mlflow.enrich_eval_result, result, since_ms=request_start_ms
                )
            except Exception:
                msg = "MLflow enrichment failed — tool scoring will degrade to content heuristics"
                logging.getLogger(__name__).warning(msg, exc_info=True)
                warnings.warn(msg, stacklevel=2)

        return result

    async def _enrich_batch(results: list[TaskResult]) -> None:
        if mlflow is None:
            return
        for result in results:
            if not result.success:
                continue
            since_ms = _start_times.pop(id(result), None)
            if since_ms is None:
                continue
            try:
                await asyncio.to_thread(
                    mlflow.enrich_eval_result, result, since_ms=since_ms
                )
            except Exception:
                msg = "MLflow enrichment failed — tool scoring will degrade to content heuristics"
                logging.getLogger(__name__).warning(msg, exc_info=True)
                warnings.warn(msg, stacklevel=2)

    _run.enrich_batch = _enrich_batch  # type: ignore[attr-defined]
    return _run
