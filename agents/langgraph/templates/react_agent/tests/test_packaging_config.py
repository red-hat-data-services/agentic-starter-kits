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


def test_makefile_exposes_auth_integration_target() -> None:
    assert re.search(r"(?m)^test-auth-integration:", MAKEFILE)
    assert "tests/integration/test_auth.py" in MAKEFILE


def test_makefile_supports_multiple_allowed_service_accounts() -> None:
    assert "AUTH_ALLOWLIST_ITEMS" in MAKEFILE
    assert "auth.allowedServiceAccounts[$$idx]" in MAKEFILE
    assert (
        len(
            re.findall(
                r'\$\$\{AUTH_ENABLED:\+--set "auth\.enabled=\$\$\{AUTH_ENABLED\}"\}',
                MAKEFILE,
            )
        )
        == 2
    )
    assert (
        len(
            re.findall(
                r'\$\$\{AUTH_ENABLED:\+--set "serviceAccount\.create=\$\$\{AUTH_ENABLED\}"\}',
                MAKEFILE,
            )
        )
        == 2
    )
    assert (
        len(
            re.findall(
                r'\$\$\{AUTH_AUDIENCE:\+--set-string "auth\.audience=\$\$\{AUTH_AUDIENCE\}"\}',
                MAKEFILE,
            )
        )
        == 2
    )


def test_env_example_documents_auth_settings() -> None:
    assert "# AUTH_ENABLED=false" in ENV_EXAMPLE
    assert "# AUTH_AUDIENCE=langgraph-react-agent" in ENV_EXAMPLE
    assert (
        "# AUTH_ALLOWED_SERVICEACCOUNTS=ci-testing:langgraph-react-agent-caller"
        in ENV_EXAMPLE
    )


def test_dockerfile_installs_auth_extra_from_staged_component() -> None:
    assert re.search(
        r"WORKDIR /opt/app-root/src/agents/langgraph/templates/react_agent",
        NORMALIZED_DOCKERFILE,
    )
    assert re.search(
        r"COPY components/auth/ /opt/app-root/src/components/auth/",
        NORMALIZED_DOCKERFILE,
    )
    assert re.search(
        r'RUN uv pip install --no-cache "\.\[tracing,auth\]"',
        NORMALIZED_DOCKERFILE,
    )


def test_pyproject_constrains_protobuf_below_7() -> None:
    dependencies = PYPROJECT["project"]["dependencies"]
    assert "protobuf<7" in dependencies
