from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
MAKEFILE = (AGENT_DIR / "Makefile").read_text(encoding="utf-8")
DOCKERFILE = (AGENT_DIR / "Dockerfile").read_text(encoding="utf-8")
ENV_EXAMPLE = (AGENT_DIR / ".env.example").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((AGENT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
NORMALIZED_MAKEFILE = re.sub(r"\s+", " ", MAKEFILE)
NORMALIZED_DOCKERFILE = re.sub(r"\s+", " ", DOCKERFILE)


def test_makefile_stages_auth_component_for_container_builds() -> None:
    copy_pattern = (
        r"mkdir -p \./components && cp -r "
        r"\.\./\.\./\.\./\.\./components/auth \./components/auth"
    )
    cleanup_pattern = (
        r"trap 'rm -rf \./images \./components/auth; "
        r"rmdir \./components 2>/dev/null \|\| true' EXIT"
    )

    assert len(re.findall(copy_pattern, NORMALIZED_MAKEFILE)) == 2
    assert len(re.findall(cleanup_pattern, NORMALIZED_MAKEFILE)) == 2


def test_makefile_has_guardrails_server_targets() -> None:
    assert re.search(r"(?m)^guardrails-server-local:", MAKEFILE)
    assert re.search(r"(?m)^guardrails-server-nemoguard:", MAKEFILE)


def test_makefile_has_tracing_stack_targets() -> None:
    assert re.search(r"(?m)^guardrails-tracing-up:", MAKEFILE)
    assert re.search(r"(?m)^guardrails-tracing-down:", MAKEFILE)


def test_makefile_server_targets_wrap_with_opentelemetry_instrument() -> None:
    # Tracing is opt-in: opentelemetry-instrument only wraps the server when
    # GUARDRAILS_TRACING_ENABLED=true, so the command is byte-identical when off.
    assert 'if [ "$${GUARDRAILS_TRACING_ENABLED:-}" = "true" ]' in MAKEFILE
    assert (
        len(re.findall(r"opentelemetry-instrument nemoguardrails server", MAKEFILE))
        == 2
    )


def test_makefile_env_installs_guardrails_extra() -> None:
    assert "--extra guardrails" in MAKEFILE


def test_env_example_points_to_guardrails_proxy() -> None:
    assert "localhost:8090" in ENV_EXAMPLE


def test_env_example_documents_auth_settings() -> None:
    assert "# AUTH_ENABLED=false" in ENV_EXAMPLE
    assert "# AUTH_AUDIENCE=langgraph-guardrailed-agent" in ENV_EXAMPLE


def test_env_example_keeps_mlflow_traces_off_otlp_export() -> None:
    # RHAIENG-7970: since mlflow 3.13, MLflow auto-exports its traces over
    # OTLP whenever OTEL_EXPORTER_OTLP_ENDPOINT is set — which the guardrails
    # OTel block in this file does when rail-level tracing is on. The active
    # MLFLOW_ENABLE_OTLP_EXPORTER=false keeps MLflow traces on the tracking
    # server when both tracing layers are enabled. Harmless when MLflow
    # tracing is off.
    assert re.search(r"(?m)^MLFLOW_ENABLE_OTLP_EXPORTER=false$", ENV_EXAMPLE)


def test_mlflow_otlp_export_respects_env_disable(monkeypatch) -> None:
    # Behavioral half of RHAIENG-7970: with the OTLP endpoint set (guardrails
    # tracing on), mlflow must not divert traces away from the tracking
    # server when MLFLOW_ENABLE_OTLP_EXPORTER=false — and would without it.
    # Skipped unless the optional tracing extra (mlflow) is installed.
    mlflow_otlp = pytest.importorskip("mlflow.tracing.utils.otlp")

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.delenv("MLFLOW_ENABLE_OTLP_EXPORTER", raising=False)
    assert mlflow_otlp.should_use_otlp_exporter() is True

    monkeypatch.setenv("MLFLOW_ENABLE_OTLP_EXPORTER", "false")
    assert mlflow_otlp.should_use_otlp_exporter() is False


def test_dockerfile_workdir_matches_agent_location() -> None:
    assert re.search(
        r"WORKDIR /opt/app-root/src/agents/langgraph/examples/guardrailed_agent",
        NORMALIZED_DOCKERFILE,
    )


def test_dockerfile_installs_auth_extra_from_staged_component() -> None:
    assert re.search(
        r"COPY components/auth/ /opt/app-root/src/components/auth/",
        NORMALIZED_DOCKERFILE,
    )
    assert re.search(
        r"RUN uv sync --frozen --no-dev --extra tracing --extra auth",
        NORMALIZED_DOCKERFILE,
    )


def test_pyproject_pins_nemoguardrails_version() -> None:
    # Pinned to the closest public release to the nemoguardrails version
    # shipped in the RHOAI 3.6 container (0.24.0.dev0). The two are not
    # API-identical, so passing local tests doesn't prove the custom actions
    # load on the cluster; run the registration check from the example
    # README's Verify section after deploying.
    guardrails_deps = PYPROJECT["project"]["optional-dependencies"]["guardrails"]
    assert any(
        "nemoguardrails[server]" in d and "==0.24.0" in d for d in guardrails_deps
    )


def test_pyproject_includes_otel_tracing_deps() -> None:
    # opentelemetry-instrument (from opentelemetry-distro) configures the OTel SDK
    # from OTEL_* env vars; the OTLP/HTTP exporter ships spans to the Collector.
    guardrails_deps = PYPROJECT["project"]["optional-dependencies"]["guardrails"]
    assert any("opentelemetry-distro" in d for d in guardrails_deps)
    assert any("opentelemetry-exporter-otlp-proto-http" in d for d in guardrails_deps)


def test_pyproject_constrains_protobuf_below_7() -> None:
    dependencies = PYPROJECT["project"]["dependencies"]
    assert "protobuf<7" in dependencies


def test_pyproject_package_name() -> None:
    assert PYPROJECT["project"]["name"] == "guardrailed_agent"


def test_makefile_default_test_excludes_integration() -> None:
    assert re.search(r"(?m)^test:", MAKEFILE)
    assert "--ignore=tests/integration" in MAKEFILE
    assert "--ignore=tests/behavioral" in MAKEFILE
    assert '-m "not guardrails_integration"' in MAKEFILE


def test_makefile_exposes_guardrails_integration_targets() -> None:
    assert re.search(r"(?m)^test-guardrails-integration:", MAKEFILE)
    assert re.search(r"(?m)^test-guardrails-integration-nemoguard:", MAKEFILE)
    assert "tests/test_guardrails.py" in MAKEFILE
    assert "-m guardrails_integration" in MAKEFILE
    assert (
        "GUARDRAILS_PROFILE=nemoguard $(MAKE) test-guardrails-integration" in MAKEFILE
    )


def test_makefile_exposes_cluster_integration_target() -> None:
    assert re.search(r"(?m)^test-integration:", MAKEFILE)
    assert "PYTHONPATH=$$(git rev-parse --show-toplevel)/tests" in MAKEFILE
    assert "tests/integration/" in MAKEFILE
    assert "-m integration" in MAKEFILE


def test_pyproject_registers_pytest_markers() -> None:
    markers = PYPROJECT["tool"]["pytest"]["ini_options"]["markers"]
    assert (
        "guardrails_integration: live NeMo Guardrails server + LLM required" in markers
    )
    assert "integration: OpenShift cluster deployment test" in markers
