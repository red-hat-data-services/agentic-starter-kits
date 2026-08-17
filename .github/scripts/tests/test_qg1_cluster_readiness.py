from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import qg1_cluster_readiness as mod  # noqa: E402


def test_parse_required_namespaces_accepts_csv_and_newlines():
    parsed = mod.parse_required_namespaces("ci-testing\nllama-serving")
    assert parsed == ["ci-testing", "llama-serving"]


def test_evaluate_cluster_state_flags_missing_namespace():
    checks = mod.evaluate_cluster_state(
        api_health="ok",
        cluster_version="4.16.12",
        gpu_nodes=["worker-gpu-0"],
        namespaces=["ci-testing"],
        required_namespaces=["ci-testing", "llama-serving"],
        require_gpu=True,
    )
    namespace_check = next(
        item for item in checks if item["name"] == "required_namespaces"
    )
    assert namespace_check["passed"] is False
    assert namespace_check["details"] == "Missing namespaces: llama-serving"


def test_evaluate_cluster_state_flags_degraded_api():
    checks = mod.evaluate_cluster_state(
        api_health="degraded",
        cluster_version="4.16.12",
        gpu_nodes=["worker-gpu-0"],
        namespaces=["ci-testing"],
        required_namespaces=["ci-testing"],
        require_gpu=True,
    )
    api_check = next(item for item in checks if item["name"] == "api_health")
    assert api_check["passed"] is False
    assert api_check["details"] == "API returned: degraded"


def test_evaluate_cluster_state_flags_empty_cluster_version():
    checks = mod.evaluate_cluster_state(
        api_health="ok",
        cluster_version="",
        gpu_nodes=["worker-gpu-0"],
        namespaces=["ci-testing"],
        required_namespaces=["ci-testing"],
        require_gpu=True,
    )
    version_check = next(item for item in checks if item["name"] == "cluster_version")
    assert version_check["passed"] is False
    assert version_check["details"] == "Cluster version unavailable"


def test_evaluate_cluster_state_gpu_required_and_present_passes():
    checks = mod.evaluate_cluster_state(
        api_health="ok",
        cluster_version="4.16.12",
        gpu_nodes=["worker-gpu-0", "worker-gpu-1"],
        namespaces=["ci-testing"],
        required_namespaces=["ci-testing"],
        require_gpu=True,
    )
    gpu_check = next(item for item in checks if item["name"] == "gpu_nodes")
    assert gpu_check["passed"] is True
    assert gpu_check["details"] == "Found 2 GPU node(s)"


def test_evaluate_cluster_state_allows_gpu_to_be_optional():
    checks = mod.evaluate_cluster_state(
        api_health="ok",
        cluster_version="4.16.12",
        gpu_nodes=[],
        namespaces=["ci-testing"],
        required_namespaces=["ci-testing"],
        require_gpu=False,
    )
    gpu_check = next(item for item in checks if item["name"] == "gpu_nodes")
    assert gpu_check["passed"] is True
    assert gpu_check["details"] == "GPU requirement disabled"


def test_build_summary_reports_overall_failure():
    checks = [
        {"name": "api_health", "passed": True, "details": "API healthy"},
        {
            "name": "required_namespaces",
            "passed": False,
            "details": "Missing namespaces: llama-serving",
        },
    ]
    summary = mod.build_summary("rhoai2", checks)
    assert summary["cluster_profile"] == "rhoai2"
    assert summary["passed"] is False
    assert summary["checks"][1]["name"] == "required_namespaces"


def test_write_outputs_creates_json_and_markdown(tmp_path):
    checks = [
        {"name": "api_health", "passed": True, "details": "API healthy"},
        {"name": "gpu_nodes", "passed": True, "details": "Found 2 GPU nodes"},
    ]
    summary = mod.build_summary("rhoai2", checks)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    mod.write_outputs(summary, json_path, md_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    markdown = md_path.read_text(encoding="utf-8")
    assert "# QG1 Cluster Readiness" in markdown
    assert "- api_health: PASS — API healthy" in markdown


def test_build_error_summary_formats_command_and_stderr():
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["oc", "get", "--raw", "/healthz"],
        output="",
        stderr="error: You must be logged in to the server (Unauthorized)",
    )
    summary = mod.build_error_summary("rhoai2", error)
    assert summary["cluster_profile"] == "rhoai2"
    assert summary["passed"] is False
    assert len(summary["checks"]) == 1
    check = summary["checks"][0]
    assert check["name"] == "oc_command"
    assert check["passed"] is False
    assert "oc get --raw /healthz" in check["details"]
    assert "Unauthorized" in check["details"]


def test_build_timeout_summary_formats_command_and_duration():
    error = subprocess.TimeoutExpired(
        cmd=["oc", "get", "--raw", "/healthz"], timeout=60
    )
    summary = mod.build_timeout_summary("rhoai2", error)
    assert summary["cluster_profile"] == "rhoai2"
    assert summary["passed"] is False
    assert len(summary["checks"]) == 1
    check = summary["checks"][0]
    assert check["name"] == "oc_command"
    assert check["passed"] is False
    assert "oc get --raw /healthz" in check["details"]
    assert "60s" in check["details"]


def test_build_error_summary_handles_missing_stderr():
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["oc", "get", "namespaces"],
        output="",
        stderr=None,
    )
    summary = mod.build_error_summary("rhoai2", error)
    assert "no stderr output" in summary["checks"][0]["details"]


def test_main_writes_failing_summary_when_oc_raises_called_process_error(
    tmp_path, monkeypatch
):
    def raise_error(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["oc", "get", "--raw", "/healthz"],
            output="",
            stderr="error: dial tcp: connection refused",
        )

    monkeypatch.setattr(mod, "run_oc", raise_error)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"

    exit_code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )

    assert exit_code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["checks"][0]["name"] == "oc_command"
    assert "connection refused" in payload["checks"][0]["details"]
    markdown = md_path.read_text(encoding="utf-8")
    assert "overall: FAIL" in markdown


def test_main_writes_failing_summary_when_oc_times_out(tmp_path, monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["oc", "get", "--raw", "/healthz"], timeout=60
        )

    monkeypatch.setattr(mod, "run_oc", raise_timeout)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"

    exit_code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )

    assert exit_code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["checks"][0]["name"] == "oc_command"
    assert "timed out" in payload["checks"][0]["details"]
    markdown = md_path.read_text(encoding="utf-8")
    assert "overall: FAIL" in markdown


def test_main_writes_passing_summary_on_happy_path(tmp_path, monkeypatch):
    responses = iter(
        [
            "ok",  # api_health
            "4.16.12",  # cluster_version
            "worker-gpu-0 worker-gpu-1",  # gpu nodes
            "ci-testing llama-serving",  # namespaces
        ]
    )

    def fake_run_oc(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"

    exit_code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--require-gpu",
            "true",
            "--required-namespaces",
            "ci-testing",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["cluster_profile"] == "rhoai2"
    assert payload["passed"] is True
    assert all(check["passed"] for check in payload["checks"])
    markdown = md_path.read_text(encoding="utf-8")
    assert "overall: PASS" in markdown


def test_run_oc_passes_timeout_to_subprocess(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = mod.run_oc("get", "--raw", "/healthz")

    assert result == "ok"
    assert captured["timeout"] == mod.OC_TIMEOUT_SECONDS
