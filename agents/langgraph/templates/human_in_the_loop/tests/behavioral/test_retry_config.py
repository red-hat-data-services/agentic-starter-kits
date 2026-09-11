"""Regression tests for the HITL behavioral evaluation wrapper."""

from __future__ import annotations

from typing import Any

import conftest
import pytest
from harness.runner import TaskConfig, TaskResult


async def test_run_eval_forwards_transient_retries(
    run_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stateless latency probe can opt in to gateway-error retries."""
    captured_config: TaskConfig | None = None

    async def fake_run_task(config: TaskConfig, client: Any = None) -> TaskResult:
        nonlocal captured_config
        captured_config = config
        return TaskResult(
            response="ok",
            tool_calls=[],
            latency_seconds=0.0,
            tokens_used=None,
            raw_response={},
            success=True,
        )

    monkeypatch.setattr(conftest, "run_task", fake_run_task)

    result = await run_eval("Hello", transient_retries=2)

    assert result.success
    assert captured_config is not None
    assert captured_config.transient_retries == 2
