"""Shared pytest fixtures for the behavioral eval framework."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Coroutine

import httpx
import pytest
import yaml
from harness.runner import TaskConfig, TaskResult, run_task

try:
    from harness.mlflow_client import MLflowTraceClient
except ImportError:
    MLflowTraceClient = None  # type: ignore[misc,assignment]


# Map agent markers to their URL env vars
_AGENT_URL_MAP = {
    "vanilla_python": "VANILLA_PYTHON_AGENT_URL",
    "langgraph_react": "REACT_AGENT_URL",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--include-cross-agent",
        action="store_true",
        default=False,
        help="Auto-include api_contract and adversarial tests when an agent marker is selected",
    )


def _marker_is_standalone(marker: str, expr: str) -> bool:
    """Return True if *marker* appears as a standalone token in *expr*,
    and is not preceded by ``not``."""
    pattern = rf"(?<!\w){re.escape(marker)}(?!\w)"
    negated = rf"\bnot\s+{re.escape(marker)}(?!\w)"
    return bool(re.search(pattern, expr)) and not re.search(negated, expr)


def pytest_configure(config: pytest.Config) -> None:
    """When an agent marker is selected with --include-cross-agent,
    auto-include cross-agent tests and set AGENT_URL from the
    agent-specific env var."""
    marker_expr = getattr(config.option, "markexpr", "")
    if not marker_expr:
        return

    include_cross = getattr(config.option, "include_cross_agent", False)

    for marker, env_var in _AGENT_URL_MAP.items():
        if _marker_is_standalone(marker, marker_expr):
            if include_cross:
                config.option.markexpr = (
                    f"({marker_expr}) or api_contract or adversarial"
                )
            if not os.environ.get("AGENT_URL"):
                agent_url = os.environ.get(env_var)
                if agent_url:
                    os.environ["AGENT_URL"] = agent_url


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Display the target agent URL and MLflow experiment at the top of the test session."""
    lines = []
    urls = []
    for var in ("AGENT_URL", "REACT_AGENT_URL", "VANILLA_PYTHON_AGENT_URL"):
        val = os.environ.get(var)
        if val:
            urls.append(f"{var}={val}")
    if not urls:
        urls.append("AGENT_URL=http://localhost:8000 (default)")
    lines.append(f"agent targets: {', '.join(urls)}")

    experiment = os.environ.get("MLFLOW_EXPERIMENT_NAME")
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    if experiment and tracking_uri:
        lines.append(f"mlflow: {tracking_uri} experiment={experiment}")

    return lines


@pytest.fixture
def agent_url() -> str:
    """Agent base URL from AGENT_URL env var or default localhost:8000."""
    return os.environ.get("AGENT_URL", "http://localhost:8000")


@pytest.fixture
def eval_config() -> dict[str, Any]:
    """Load threshold configuration from configs/thresholds.yaml."""
    config_path = Path(__file__).parent / "configs" / "thresholds.yaml"
    if not config_path.exists():
        pytest.skip(f"Threshold config not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async httpx client that is closed after the test."""
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def run_eval(
    agent_url: str, http_client: httpx.AsyncClient
) -> Callable[..., Coroutine[Any, Any, TaskResult]]:
    """Convenience fixture that wraps run_task with the session's agent URL and client.

    Usage in tests:
        async def test_something(run_eval):
            result = await run_eval("What is the weather in Denver?")
            assert result.success
    """

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
        return await run_task(config, client=http_client)

    return _run


@pytest.fixture
def mlflow_client() -> "MLflowTraceClient | None":
    """Provide an MLflow trace client if configured via env vars.

    Set MLFLOW_TRACKING_URI and MLFLOW_EXPERIMENT_NAME to enable.
    Returns None if mlflow is not installed or env vars are not set.
    """
    if MLflowTraceClient is None:
        return None
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    experiment_name = os.environ.get("MLFLOW_EXPERIMENT_NAME")
    if not tracking_uri or not experiment_name:
        return None
    return MLflowTraceClient(tracking_uri, experiment_name)
