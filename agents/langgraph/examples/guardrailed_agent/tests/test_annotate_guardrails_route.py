"""Unit tests for deploy/scripts/annotate_guardrails_route.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = AGENT_DIR / "deploy" / "scripts" / "annotate_guardrails_route.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "annotate_guardrails_route", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def annotate_module():
    return _load_module()


def test_wait_for_route_and_annotate_polls_then_annotates(
    annotate_module, monkeypatch
) -> None:
    hosts = iter(["", "guardrails.example.com"])
    annotate_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        annotate_module,
        "get_route_host",
        lambda route_name, namespace, oc="oc": next(hosts),
    )
    monkeypatch.setattr(
        annotate_module,
        "annotate_route_timeout",
        lambda route_name, namespace, timeout, oc="oc": annotate_calls.append(
            (route_name, namespace, timeout)
        ),
    )
    monkeypatch.setattr(annotate_module, "sleep", lambda _seconds: None)

    host = annotate_module.wait_for_route_and_annotate(
        "langgraph-guardrailed-agent-guardrails",
        "ci-testing",
        attempts=2,
        interval_seconds=0,
    )

    assert host == "guardrails.example.com"
    assert annotate_calls == [
        ("langgraph-guardrailed-agent-guardrails", "ci-testing", "120s")
    ]


def test_wait_for_route_and_annotate_fails_when_route_missing(
    annotate_module, monkeypatch
) -> None:
    monkeypatch.setattr(
        annotate_module, "get_route_host", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(annotate_module, "sleep", lambda _seconds: None)

    with pytest.raises(
        SystemExit, match="Route 'langgraph-guardrailed-agent-guardrails'"
    ):
        annotate_module.wait_for_route_and_annotate(
            "langgraph-guardrailed-agent-guardrails",
            "ci-testing",
            attempts=2,
            interval_seconds=0,
        )


def test_annotate_route_timeout_invokes_oc(annotate_module, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(annotate_module.subprocess, "run", fake_run)

    annotate_module.annotate_route_timeout(
        "langgraph-guardrailed-agent-guardrails",
        "ci-testing",
        "120s",
    )

    assert calls == [
        [
            "oc",
            "annotate",
            "route",
            "langgraph-guardrailed-agent-guardrails",
            "-n",
            "ci-testing",
            "haproxy.router.openshift.io/timeout=120s",
            "--overwrite",
        ]
    ]
