#!/usr/bin/env python3
"""Tests for the quality-gates-pipeline Slack summary builder."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "build_qg_summary.sh"


def write_outcome(directory: Path, name: str, payload: dict) -> None:
    prefix = "qg4-outcome" if "qg4" in directory.name else "qg7-outcome"
    outcome_dir = directory / f"{prefix}-{name}"
    outcome_dir.mkdir(parents=True, exist_ok=True)
    (outcome_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def run_summary(env_overrides: dict, qg4_dir: Path, qg7_dir: Path) -> str:
    env = os.environ.copy()
    env.update(env_overrides)
    env["QG4_OUTCOMES_DIR"] = str(qg4_dir)
    env["QG7_OUTCOMES_DIR"] = str(qg7_dir)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def test_gate_summary_only_when_qg4_never_ran(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    output = run_summary(
        {
            "QG1_RESULT": "failure",
            "QG2_RESULT": "skipped",
            "QG4_RESULT": "skipped",
            "QG7_RESULT": "skipped",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "Gate Summary" in output
    assert "QG1" in output and "failure" in output
    assert "blocked by QG1" in output
    assert "QG4 did not run" in output
    assert "Agent Results" not in output


def test_qg7_skip_reports_qg4_collection_failure(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "failure",
            "QG7_RESULT": "skipped",
            "COLLECT_QG4_RESULT": "failure",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "QG4 result collection failed" in output
    assert "no agents eligible" not in output


def test_agent_matrix_reflects_qg4_and_qg7_outcomes(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    write_outcome(
        qg4_dir,
        "langgraph-react-agent",
        {
            "name": "langgraph-react-agent",
            "dir": "agents/langgraph/templates/react_agent",
            "status": "success",
        },
    )
    write_outcome(
        qg4_dir,
        "langgraph-hitl-agent",
        {
            "name": "langgraph-hitl-agent",
            "dir": "agents/langgraph/templates/human_in_the_loop",
            "status": "failure",
        },
    )
    write_outcome(
        qg4_dir,
        "langgraph-guardrailed-agent",
        {
            "name": "langgraph-guardrailed-agent",
            "dir": "agents/langgraph/examples/guardrailed_agent",
            "status": "success",
        },
    )
    write_outcome(
        qg7_dir,
        "langgraph-react-agent",
        {"name": "langgraph-react-agent", "status": "success"},
    )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "failure",
            "QG7_RESULT": "success",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "Agent Results" in output
    assert "langgraph-react-agent" in output
    assert "blocked: failed QG4" in output
    assert "excluded from QG7" in output


def test_malformed_outcome_file_does_not_crash_script(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    write_outcome(
        qg4_dir,
        "agent-good",
        {
            "name": "agent-good",
            "dir": "agents/langgraph/templates/agent_good",
            "status": "success",
        },
    )
    bad_dir = qg4_dir / "qg4-outcome-agent-bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "result.json").write_text(
        '{"name":"agent-bad","dir":"agents/lang', encoding="utf-8"
    )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "failure",
            "QG7_RESULT": "skipped",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "Gate Summary" in output
    assert "agent-good" in output
    assert "could not be parsed" in output


def test_agent_table_truncates_beyond_char_budget(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    for i in range(10):
        write_outcome(
            qg4_dir,
            f"agent-{i:02d}",
            {
                "name": f"agent-{i:02d}",
                "dir": f"agents/langgraph/templates/agent_{i:02d}",
                "status": "success",
            },
        )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "success",
            "QG7_RESULT": "skipped",
            "TOTAL_CHAR_BUDGET": "550",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "agent-00" in output
    assert "agent-02" in output
    assert "agent-09" not in output
    assert "more agent(s)" in output
    assert len(output) <= 3000


def test_agent_table_stays_under_slack_limit_with_many_long_names(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    # Mirrors the longest real agent name in the repo's QG4 matrix
    # (vanilla-python-openai-responses-agent, 37 chars) at a scale (100
    # agents) approaching the repo's long-term template count target.
    long_name = "vanilla-python-openai-responses-agent"
    for i in range(100):
        name = f"{long_name}-{i:03d}"
        write_outcome(
            qg4_dir,
            name,
            {
                "name": name,
                "dir": f"agents/vanilla_python/templates/{name}",
                "status": "success",
            },
        )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "success",
            "QG7_RESULT": "skipped",
        },
        qg4_dir,
        qg7_dir,
    )

    assert len(output) <= 3000
    assert "more agent(s)" in output


def test_cancelled_agent_rendered_distinctly_from_skipped(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    write_outcome(
        qg4_dir,
        "agent-cancelled",
        {
            "name": "agent-cancelled",
            "dir": "agents/langgraph/templates/agent_cancelled",
            "status": "cancelled",
        },
    )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "cancelled",
            "QG7_RESULT": "skipped",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "⏱️" in output
    assert "agent-cancelled" in output


def test_agent_not_run_when_qg7_outcomes_missing(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    write_outcome(
        qg4_dir,
        "langgraph-react-agent",
        {
            "name": "langgraph-react-agent",
            "dir": "agents/langgraph/templates/react_agent",
            "status": "success",
        },
    )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "success",
            "QG7_RESULT": "skipped",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "QG7 did not run" in output


def test_qg4_download_failure_keeps_agent_results_section(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "failure",
            "QG7_RESULT": "skipped",
            "QG4_ARTIFACT_DOWNLOAD_RESULT": "failure",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "Agent Results" in output
    assert "QG4 outcome artifact download failed" in output


def test_qg7_download_failure_is_visible_in_agent_results(tmp_path):
    qg4_dir = tmp_path / "qg4-outcomes"
    qg7_dir = tmp_path / "qg7-outcomes"
    qg4_dir.mkdir()
    qg7_dir.mkdir()
    write_outcome(
        qg4_dir,
        "agent-good",
        {
            "name": "agent-good",
            "dir": "agents/langgraph/templates/agent_good",
            "status": "success",
        },
    )

    output = run_summary(
        {
            "QG1_RESULT": "success",
            "QG2_RESULT": "success",
            "QG4_RESULT": "success",
            "QG7_RESULT": "failure",
            "QG7_ARTIFACT_DOWNLOAD_RESULT": "failure",
        },
        qg4_dir,
        qg7_dir,
    )

    assert "Agent Results" in output
    assert "QG7 outcome unavailable" in output
    assert "QG7 outcome artifact download failed" in output
