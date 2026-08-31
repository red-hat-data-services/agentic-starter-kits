from __future__ import annotations

from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = AGENT_ROOT / "Dockerfile"
EXPECTED_BASE_IMAGE = (
    "registry.access.redhat.com/ubi9/python-312"
    "@sha256:e95978812895b9abb2bdc109b501078da2a47c8dbb9fa23758af40ed50ab6023"
)
EXPECTED_UV_COPY_LINE = (
    "COPY --from=ghcr.io/astral-sh/uv@sha256:"
    "fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce "
    "/uv /usr/local/bin/uv"
)
EXPECTED_INSTALL_LINE = "RUN uv sync --frozen --no-dev --extra tracing"
EXPECTED_SQLITE_INSTALL_LINE = "RUN uv sync --frozen --no-dev --extra tracing \\"
EXPECTED_SQLITE_SHIM = 'sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")'


def test_dockerfile_uses_pinned_ubi9_base_image():
    from_lines = [
        line.strip()
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("FROM ")
    ]

    assert from_lines
    assert from_lines[0] == f"FROM {EXPECTED_BASE_IMAGE}"


def test_dockerfile_installs_dependencies_with_ubi_python_environment():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert EXPECTED_INSTALL_LINE in dockerfile


def test_dockerfile_pins_uv_build_stage_by_digest():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert EXPECTED_UV_COPY_LINE in dockerfile


def test_dockerfile_installs_sqlite_compat_shim_for_chromadb():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert EXPECTED_SQLITE_INSTALL_LINE in dockerfile
    assert EXPECTED_SQLITE_SHIM in dockerfile
