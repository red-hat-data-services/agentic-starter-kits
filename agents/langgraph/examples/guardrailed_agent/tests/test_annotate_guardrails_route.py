"""Tests for annotate_guardrails_route.py using a fake oc executable."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = AGENT_DIR / "deploy" / "scripts" / "annotate_guardrails_route.py"


def _write_fake_oc(tmp_path: Path, body: str) -> Path:
    oc = tmp_path / "oc"
    oc.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    oc.chmod(0o755)
    return oc


def _run_script(
    oc: Path,
    *extra_args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = {
        **os.environ,
        "OC_BIN": str(oc),
        "POLL_ATTEMPTS": "3",
        "POLL_INTERVAL_SECONDS": "0",
        "OC_TIMEOUT_SECONDS": "2",
        **(env or {}),
    }
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--route-name",
            "test-route",
            "--namespace",
            "test-ns",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=run_env,
    )


def test_annotates_route_when_present(tmp_path: Path) -> None:
    oc = _write_fake_oc(
        tmp_path,
        """
case "$1" in
get)
  if [ "$2" = "route" ]; then printf '%s' "my-route.example.com"; fi
  ;;
annotate) exit 0 ;;
esac
""",
    )
    result = _run_script(oc)
    assert result.returncode == 0
    assert "Route URL: https://my-route.example.com" in result.stdout


def test_polls_until_route_appears(tmp_path: Path) -> None:
    state = tmp_path / "state"
    oc = _write_fake_oc(
        tmp_path,
        f"""
STATE_FILE="{state}"
case "$1" in
get)
  if [ "$2" = "route" ]; then
    count=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
    count=$((count + 1))
    echo "$count" > "$STATE_FILE"
    if [ "$count" -ge 2 ]; then printf '%s' "delayed.example.com"; fi
  fi
  ;;
annotate) exit 0 ;;
esac
""",
    )
    result = _run_script(oc)
    assert result.returncode == 0
    assert "Route URL: https://delayed.example.com" in result.stdout


def test_optional_missing_route_exits_zero(tmp_path: Path) -> None:
    oc = _write_fake_oc(
        tmp_path,
        """
case "$1" in
get) ;;
annotate) exit 0 ;;
esac
""",
    )
    result = _run_script(oc)
    assert result.returncode == 0
    assert "WARNING:" in result.stderr
    assert "not found" in result.stderr


def test_required_missing_route_exits_one(tmp_path: Path) -> None:
    oc = _write_fake_oc(
        tmp_path,
        """
case "$1" in
get) ;;
annotate) exit 0 ;;
esac
""",
    )
    result = _run_script(oc, "--required")
    assert result.returncode == 1
    assert "ERROR:" in result.stderr
    assert "not found" in result.stderr


def test_annotate_failure_exits_one(tmp_path: Path) -> None:
    oc = _write_fake_oc(
        tmp_path,
        """
case "$1" in
get)
  if [ "$2" = "route" ]; then printf '%s' "my-route.example.com"; fi
  ;;
annotate)
  echo "permission denied" >&2
  exit 1
  ;;
esac
""",
    )
    result = _run_script(oc)
    assert result.returncode == 1
    assert "Failed to annotate route" in result.stderr


def test_oc_timeout_exits_one(tmp_path: Path) -> None:
    oc = _write_fake_oc(
        tmp_path,
        """
case "$1" in
get) sleep 5 ;;
annotate) exit 0 ;;
esac
""",
    )
    result = _run_script(oc, env={"OC_TIMEOUT_SECONDS": "1"})
    assert result.returncode == 1
    assert "timed out" in result.stderr
