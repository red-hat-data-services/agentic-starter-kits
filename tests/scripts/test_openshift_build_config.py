from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "openshift-build-config.sh"

CLEANUP_DENYLIST = (
    "postgres",
    "minio",
    "mcp-automl",
    "langflow-simple-tool-calling-agent",
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exists():
    assert SCRIPT.is_file()


def test_patch_history_requires_agent_name():
    result = run_script("patch-history")
    assert result.returncode != 0
    assert "agent name" in result.stderr.lower() or "usage" in result.stderr.lower()


def test_cleanup_requires_agent_name():
    result = run_script("cleanup")
    assert result.returncode != 0


@pytest.mark.parametrize("denylisted", CLEANUP_DENYLIST)
def test_cleanup_rejects_denylisted_names(denylisted: str):
    result = run_script("cleanup", denylisted)
    assert result.returncode == 1
    assert "denylisted" in result.stderr.lower() or "refusing" in result.stderr.lower()
    assert denylisted in result.stderr


def test_cleanup_skips_when_oc_missing():
    result = subprocess.run(
        [str(SCRIPT), "cleanup", "langgraph-react-agent"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert "skipping" in result.stderr.lower()


def test_patch_history_fails_when_oc_patch_fails(tmp_path: Path):
    fake_oc = tmp_path / "oc"
    fake_oc.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == patch ]]; then\n'
        '  echo "patch failed" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    fake_oc.chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), "patch-history", "langgraph-react-agent", "-n", "ci-testing"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "patch failed" in result.stderr
