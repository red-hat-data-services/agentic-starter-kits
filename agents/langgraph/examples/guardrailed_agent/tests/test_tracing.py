from __future__ import annotations

import os
import sys
import types

import pytest
from guardrailed_agent import tracing


@pytest.fixture(autouse=True)
def isolated_environ(monkeypatch):
    # enable_tracing() writes os.environ directly (setdefault), which
    # monkeypatch can't undo; give each test a throwaway copy instead.
    monkeypatch.setattr(os, "environ", dict(os.environ))


@pytest.fixture
def unreachable_mlflow(monkeypatch):
    """Run enable_tracing() up to the health check without a real MLflow.

    Stubs the mlflow modules (the tracing extra may not be installed), makes
    the health check fail so enable_tracing() returns early, and disables
    load_dotenv() so a developer's local .env can't leak into the test.
    """
    mlflow_stub = types.ModuleType("mlflow")
    mlflow_stub.langchain = types.ModuleType("mlflow.langchain")
    monkeypatch.setitem(sys.modules, "mlflow", mlflow_stub)
    monkeypatch.setitem(sys.modules, "mlflow.langchain", mlflow_stub.langchain)
    monkeypatch.setattr(tracing, "load_dotenv", lambda: None)

    def fail_health_check(**_kwargs):
        raise RuntimeError("unreachable")

    monkeypatch.setattr(tracing, "check_mlflow_health", fail_health_check)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")


def test_enable_tracing_defaults_mlflow_otlp_export_off(
    unreachable_mlflow, monkeypatch
) -> None:
    # RHAIENG-7970: rail-level tracing sets OTEL_EXPORTER_OTLP_ENDPOINT, which
    # would otherwise divert MLflow traces to the guardrails collector.
    monkeypatch.delenv("MLFLOW_ENABLE_OTLP_EXPORTER", raising=False)
    tracing.enable_tracing()
    assert os.environ["MLFLOW_ENABLE_OTLP_EXPORTER"] == "false"


def test_enable_tracing_keeps_explicit_mlflow_otlp_export(
    unreachable_mlflow, monkeypatch
) -> None:
    monkeypatch.setenv("MLFLOW_ENABLE_OTLP_EXPORTER", "true")
    tracing.enable_tracing()
    assert os.environ["MLFLOW_ENABLE_OTLP_EXPORTER"] == "true"


def test_enable_tracing_leaves_env_alone_when_tracing_disabled(monkeypatch) -> None:
    monkeypatch.setattr(tracing, "load_dotenv", lambda: None)
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_ENABLE_OTLP_EXPORTER", raising=False)
    tracing.enable_tracing()
    assert "MLFLOW_ENABLE_OTLP_EXPORTER" not in os.environ
