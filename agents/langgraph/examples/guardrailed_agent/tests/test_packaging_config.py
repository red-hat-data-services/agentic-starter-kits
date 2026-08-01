from __future__ import annotations

import re
import tomllib
from pathlib import Path

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


def test_makefile_env_installs_guardrails_extra() -> None:
    assert "--extra guardrails" in MAKEFILE


def test_env_example_points_to_guardrails_proxy() -> None:
    assert "localhost:8090" in ENV_EXAMPLE


def test_env_example_documents_auth_settings() -> None:
    assert "# AUTH_ENABLED=false" in ENV_EXAMPLE
    assert "# AUTH_AUDIENCE=langgraph-guardrailed-agent" in ENV_EXAMPLE


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
        r'RUN uv pip install --no-cache "\.\[tracing,auth\]"',
        NORMALIZED_DOCKERFILE,
    )


def test_pyproject_pins_nemoguardrails_version() -> None:
    guardrails_deps = PYPROJECT["project"]["optional-dependencies"]["guardrails"]
    assert "nemoguardrails[server]==0.21.0" in guardrails_deps


def test_pyproject_constrains_protobuf_below_7() -> None:
    dependencies = PYPROJECT["project"]["dependencies"]
    assert "protobuf<7" in dependencies


def test_pyproject_package_name() -> None:
    assert PYPROJECT["project"]["name"] == "guardrailed_agent"


def test_makefile_default_test_excludes_integration() -> None:
    assert re.search(r"(?m)^test:", MAKEFILE)
    assert "--ignore=tests/integration" in MAKEFILE
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
