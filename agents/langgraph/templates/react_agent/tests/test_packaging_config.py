from __future__ import annotations

from pathlib import Path
import tomllib


AGENT_DIR = Path(__file__).resolve().parents[1]
MAKEFILE = (AGENT_DIR / "Makefile").read_text(encoding="utf-8")
DOCKERFILE = (AGENT_DIR / "Dockerfile").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((AGENT_DIR / "pyproject.toml").read_text(encoding="utf-8"))


def test_makefile_stages_auth_component_for_container_builds() -> None:
    expected_copy = "mkdir -p ./components && cp -r ../../../../components/auth ./components/auth"
    expected_cleanup = (
        "trap 'rm -rf ./images ./components/auth; "
        "rmdir ./components 2>/dev/null || true' EXIT"
    )

    assert MAKEFILE.count(expected_copy) == 2
    assert MAKEFILE.count(expected_cleanup) == 2


def test_makefile_exposes_auth_integration_target() -> None:
    assert "test-auth-integration:" in MAKEFILE
    assert "tests/integration/test_auth.py" in MAKEFILE


def test_makefile_forwards_auth_settings_during_render_and_deploy() -> None:
    assert (
        'AUTH_ALLOWLIST="$${AUTH_ALLOWED_SERVICEACCOUNTS:-$${AUTH_ALLOWED_SERVICEACCOUNT}}"'
        in MAKEFILE
    )
    assert MAKEFILE.count('$${AUTH_ENABLED:+--set "auth.enabled=$${AUTH_ENABLED}"}') == 2
    assert MAKEFILE.count(
        '$${AUTH_ENABLED:+--set "serviceAccount.create=$${AUTH_ENABLED}"}'
    ) == 2
    assert MAKEFILE.count(
        '$${AUTH_AUDIENCE:+--set-string "auth.audience=$${AUTH_AUDIENCE}"}'
    ) == 2
    assert MAKEFILE.count(
        '$${AUTH_ALLOWLIST:+--set-string "auth.allowedServiceAccounts[0]=$${AUTH_ALLOWLIST}"}'
    ) == 2


def test_dockerfile_installs_auth_extra_from_staged_component() -> None:
    assert "WORKDIR /opt/app-root/src/agents/langgraph/templates/react_agent" in DOCKERFILE
    assert "COPY components/auth/ /opt/app-root/src/components/auth/" in DOCKERFILE
    assert 'RUN uv pip install --no-cache ".[tracing,auth]"' in DOCKERFILE


def test_pyproject_constrains_protobuf_below_7() -> None:
    dependencies = PYPROJECT["project"]["dependencies"]
    assert "protobuf<7" in dependencies
