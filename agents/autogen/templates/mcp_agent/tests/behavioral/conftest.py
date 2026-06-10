"""Fixtures for AutoGen MCP agent evals."""

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


@pytest.fixture
def agent_url() -> str:
    """AutoGen MCP agent URL from AUTOGEN_MCP_AGENT_URL env var or default localhost:8000."""
    return os.environ.get("AUTOGEN_MCP_AGENT_URL", "http://localhost:8000")


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
    raise FileNotFoundError(
        "Could not find repo root (no tests/behavioral/configs/thresholds.yaml)"
    )


@pytest.fixture
def eval_config() -> dict[str, Any]:
    """Load threshold configuration from the shared configs directory."""
    config_path = (
        _find_repo_root() / "tests" / "behavioral" / "configs" / "thresholds.yaml"
    )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


FIXTURES_DIR = Path(__file__).parent / "fixtures"
# AutoGen MCP exposes tool_invocations only in non-streaming JSON responses.
STREAM = False


def load_golden(category: str | None = None) -> list[dict[str, Any]]:
    """Load golden queries from the fixtures directory, optionally filtering by category."""
    return _load_golden_from(FIXTURES_DIR, category)


@pytest.fixture
def known_tools() -> list[str]:
    """Tools available on the AutoGen MCP agent (excluding invoke_churn)."""
    return ["add", "sub"]


@pytest.fixture
def autogen_mcp_thresholds(eval_config: dict[str, Any]) -> dict[str, Any]:
    """Load the autogen_mcp section from the shared thresholds config."""
    return eval_config["autogen_mcp"]


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

        if mlflow is not None and result.success:
            try:
                await asyncio.to_thread(
                    mlflow.enrich_eval_result, result, since_ms=request_start_ms
                )
            except Exception:
                msg = "MLflow enrichment failed — tool scoring will degrade to content heuristics"
                logging.getLogger(__name__).warning(msg, exc_info=True)
                warnings.warn(msg, stacklevel=2)

        return result

    return _run
