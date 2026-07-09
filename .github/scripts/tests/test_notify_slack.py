#!/usr/bin/env python3
"""Tests for the Slack notification helper scripts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTIFY_DIR = REPO_ROOT / ".github" / "actions" / "notify-slack"
RENDER_SCRIPT = NOTIFY_DIR / "render_payload.sh"
NOTIFY_SCRIPT = NOTIFY_DIR / "notify.sh"
SHOULD_NOTIFY_SCRIPT = NOTIFY_DIR / "should_notify.sh"
EXTRACT_FAILED_JOBS_SCRIPT = NOTIFY_DIR / "extract_failed_jobs.sh"


def parse_key_value_output(stdout: str) -> dict[str, str]:
    pairs = {}
    for line in stdout.strip().splitlines():
        key, value = line.split("=", 1)
        pairs[key] = value
    return pairs


def test_render_payload_includes_failed_jobs_and_links():
    env = os.environ.copy()
    env.update(
        {
            "WORKFLOW_NAME": "Code Quality",
            "EVENT_NAME": "workflow_dispatch",
            "REF_NAME": "main",
            "STATUS": "failure",
            "RUN_URL": "https://github.com/example/repo/actions/runs/123",
            "DASHBOARD_URL": "https://red-hat-data-services.github.io/agentic-starter-kits/",
            "REPOSITORY": "red-hat-data-services/agentic-starter-kits",
            "FAILED_JOBS_JSON": json.dumps(["lint", "type-check"]),
            "TIMESTAMP": "2026-07-09T07:30:00Z",
        }
    )

    result = subprocess.run(
        ["bash", str(RENDER_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["attachments"][0]["color"] == "#d00000"

    payload_text = json.dumps(payload)
    assert "Code Quality" in payload_text
    assert "workflow_dispatch" in payload_text
    assert "main" in payload_text
    assert "lint" in payload_text
    assert "type-check" in payload_text
    assert "https://github.com/example/repo/actions/runs/123" in payload_text
    assert (
        "https://red-hat-data-services.github.io/agentic-starter-kits/" in payload_text
    )


def test_notify_preview_prints_payload(tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({"text": "preview payload", "blocks": []}), encoding="utf-8"
    )

    result = subprocess.run(
        ["bash", str(NOTIFY_SCRIPT), "--preview", str(payload_path)],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert "Slack payload preview" in result.stdout
    assert "preview payload" in result.stdout


def test_notify_ignores_legacy_secret_env(tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({"text": "legacy secret should be ignored"}), encoding="utf-8"
    )

    env = os.environ.copy()
    env.pop("SLACK_WEBHOOK_URL", None)
    env.pop("SLACK_WEBHOOK_URLS", None)
    env["WH_SLACK_TEAM_LLS_CORE"] = "https://hooks.slack.com/services/legacy/test/value"

    result = subprocess.run(
        ["bash", str(NOTIFY_SCRIPT), str(payload_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "Slack webhook not configured" in result.stdout


def test_notify_ignores_multi_webhook_env(tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({"text": "multi webhook env should be ignored"}), encoding="utf-8"
    )

    env = os.environ.copy()
    env.pop("SLACK_WEBHOOK_URL", None)
    env["SLACK_WEBHOOK_URLS"] = "https://hooks.slack.com/services/one,test"

    result = subprocess.run(
        ["bash", str(NOTIFY_SCRIPT), str(payload_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "Slack webhook not configured" in result.stdout


def test_extract_failed_jobs_filters_matrix_results(tmp_path):
    payload_path = tmp_path / "jobs.json"
    payload_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"name": "verify-cluster-connection", "conclusion": "success"},
                    {
                        "name": "test-agent (langgraph-react-agent)",
                        "conclusion": "failure",
                    },
                    {
                        "name": "test-agent (google-adk-agent)",
                        "conclusion": "cancelled",
                    },
                    {
                        "name": "test-agent (crewai-websearch-agent)",
                        "conclusion": "timed_out",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(EXTRACT_FAILED_JOBS_SCRIPT), str(payload_path)],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    failed_jobs = json.loads(result.stdout)
    assert failed_jobs == [
        "test-agent (langgraph-react-agent)",
        "test-agent (google-adk-agent)",
        "test-agent (crewai-websearch-agent)",
    ]


def test_should_notify_for_main_failure():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "push",
            "REF_NAME": "main",
            "NEEDS_JSON": json.dumps({"lint": {"result": "failure"}}),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "true"
    assert output["status"] == "failure"


def test_should_not_notify_on_all_success():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "push",
            "REF_NAME": "main",
            "NEEDS_JSON": json.dumps(
                {
                    "lint": {"result": "success"},
                    "type-check": {"result": "success"},
                }
            ),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "false"
    assert output["status"] == "success"


def test_should_not_notify_for_pull_request_failure():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "pull_request",
            "REF_NAME": "main",
            "NEEDS_JSON": json.dumps({"lint": {"result": "failure"}}),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "false"
    assert output["status"] == "success"


def test_should_not_notify_for_feature_branch_manual_dispatch():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "workflow_dispatch",
            "REF_NAME": "feature-branch",
            "NEEDS_JSON": json.dumps({"test-agent": {"result": "failure"}}),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "false"
    assert output["status"] == "success"


def test_should_notify_for_matrix_failure():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "schedule",
            "REF_NAME": "main",
            "NEEDS_JSON": json.dumps(
                {
                    "verify-cluster-connection": {"result": "success"},
                    "test-agent": {"result": "failure"},
                }
            ),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "true"
    assert output["status"] == "failure"


def test_should_notify_for_cancelled_run():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "workflow_dispatch",
            "REF_NAME": "main",
            "NEEDS_JSON": json.dumps({"lint": {"result": "cancelled"}}),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "true"
    assert output["status"] == "cancelled"


def test_should_notify_for_timed_out_run():
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "push",
            "REF_NAME": "main",
            "NEEDS_JSON": json.dumps({"lint": {"result": "timed_out"}}),
        }
    )

    result = subprocess.run(
        ["bash", str(SHOULD_NOTIFY_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = parse_key_value_output(result.stdout)
    assert output["should_notify"] == "true"
    assert output["status"] == "timed_out"
