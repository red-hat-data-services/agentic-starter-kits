"""Fixtures for Langflow Simple Tool Calling agent evals."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Coroutine

import httpx
import pytest
import yaml
from harness.fixtures import load_golden as _load_golden_from
from harness.runner import TaskConfig, TaskResult, run_task


@pytest.fixture
def agent_url() -> str:
    """Langflow agent URL from env var or default localhost."""
    return os.environ.get("LANGFLOW_TOOL_CALLING_AGENT_URL", "http://localhost:7860")


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


TOOL_OUTPUT_EVIDENCE = [
    "°c",
    "°f",
    "precipitation",
    "km/h",
    "national park",
    "nps.gov",
    "alert",
    "closure",
]

FIXTURES_DIR = Path(__file__).parent / "fixtures"
STREAM = False


def load_golden(category: str | None = None) -> list[dict[str, Any]]:
    """Load golden queries from the fixtures directory, optionally filtering by category."""
    return _load_golden_from(FIXTURES_DIR, category)


@pytest.fixture
def flow_id() -> str:
    """Langflow flow ID from env var — required for test execution."""
    fid = os.environ.get("LANGFLOW_FLOW_ID", "")
    if not fid:
        pytest.skip("LANGFLOW_FLOW_ID is required — discover via GET /api/v1/flows/")
    return fid


@pytest.fixture
def known_tools() -> list[str]:
    """Tools available on the Langflow Simple Tool Calling agent."""
    return ["get_forecast", "search_parks", "get_alerts"]


@pytest.fixture
def langflow_tool_calling_thresholds(eval_config: dict[str, Any]) -> dict[str, Any]:
    """Load the langflow_tool_calling section from the shared thresholds config."""
    return eval_config["langflow_tool_calling"]


@pytest.fixture
def run_eval(
    agent_url: str, http_client: httpx.AsyncClient, flow_id: str
) -> Callable[..., Coroutine[Any, Any, TaskResult]]:
    """Run eval against the Langflow agent.

    Tool calls are extracted from the Langflow /api/v1/run response
    content_blocks by the harness runner — no MLflow enrichment needed.
    """

    async def _run(
        query: str,
        expected_tools: list[str] | None = None,
        timeout_seconds: float = 45.0,
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
            api_format="langflow_run",
            flow_id=flow_id,
        )
        result = await run_task(config, client=http_client)
        return result

    async def _enrich_batch(results: list[TaskResult]) -> None:  # noqa: ARG001
        return  # Langflow does not use MLflow enrichment

    _run.enrich_batch = _enrich_batch  # type: ignore[attr-defined]
    return _run
