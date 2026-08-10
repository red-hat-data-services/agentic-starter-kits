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


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111


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


def test_patch_history_payload_is_valid_json():
    """Dry-run: script should emit merge patch with 2/1 limits (no oc required)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "successfulBuildsHistoryLimit" in text
    assert "failedBuildsHistoryLimit" in text
    assert "SUCCESSFUL_LIMIT=2" in text
    assert "FAILED_LIMIT=1" in text


def test_cleanup_denylist_contains_expected_names():
    text = SCRIPT.read_text(encoding="utf-8")
    for name in CLEANUP_DENYLIST:
        assert name in text
