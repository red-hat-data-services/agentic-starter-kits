"""Fixtures for LangGraph Human-in-the-Loop agent evals."""

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
    """HITL agent URL from HITL_AGENT_URL env var or default localhost:8000."""
    return os.environ.get("HITL_AGENT_URL", "http://localhost:8000")


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
    """Tools available on the LangGraph HITL agent."""
    return ["create_file"]


@pytest.fixture
def hitl_thresholds(eval_config: dict[str, Any]) -> dict[str, Any]:
    """Load the langgraph_hitl section from the shared thresholds config."""
    return eval_config["langgraph_hitl"]


async def _send_approval(
    client: httpx.AsyncClient,
    agent_url: str,
    thread_id: str,
    approval: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Send an approval/rejection follow-up to a pending HITL interrupt."""
    url = f"{agent_url.rstrip('/')}/chat/completions"
    payload = {
        "messages": [{"role": "user", "content": ""}],
        "stream": False,
        "thread_id": thread_id,
        "approval": approval,
    }
    resp = await client.post(url, json=payload, timeout=timeout_seconds)
    resp.raise_for_status()
    return resp.json()


@pytest.fixture
def run_eval(
    agent_url: str, http_client: httpx.AsyncClient
) -> Callable[..., Coroutine[Any, Any, TaskResult]]:
    """Run eval with HITL approval flow and MLflow enrichment.

    When the agent returns finish_reason="pending_approval", this fixture
    automatically sends the approval follow-up specified by the `approval`
    parameter ("yes" or "no") and returns the final response for scoring.
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
        approval: str | None = None,
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

        if result.success and approval is not None:
            raw = result.raw_response
            finish = raw.get("choices", [{}])[0].get("finish_reason", "") if raw else ""
            thread_id = raw.get("thread_id", "") if raw else ""
            if finish != "pending_approval" or not thread_id:
                warnings.warn(
                    f"approval='{approval}' requested but agent did not return "
                    f"pending_approval (finish_reason='{finish}', "
                    f"thread_id='{thread_id}'). Approval step skipped.",
                    stacklevel=2,
                )
            if finish == "pending_approval" and thread_id:
                followup_start = time.monotonic()
                followup = await _send_approval(
                    http_client, agent_url, thread_id, approval, timeout_seconds
                )
                followup_latency = time.monotonic() - followup_start
                followup_content = (
                    followup.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                result = TaskResult(
                    response=followup_content,
                    tool_calls=result.tool_calls,
                    latency_seconds=result.latency_seconds + followup_latency,
                    tokens_used=result.tokens_used,
                    raw_response=followup,
                    success=True,
                    error=None,
                )
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
