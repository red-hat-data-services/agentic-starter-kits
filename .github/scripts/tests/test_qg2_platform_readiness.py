from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import qg2_platform_readiness as mod  # noqa: E402


def test_operator_check_passes_when_ready_replicas_meet_desired():
    check = mod.evaluate_operator_state(
        cluster_type="rhoai",
        deployment_exists=True,
        ready_replicas="1",
        desired_replicas="1",
        csv_phases=[],
    )
    assert check["passed"] is True
    assert "ready replicas: 1/1" in check["details"]


def test_operator_check_fails_when_deployment_exists_but_ready_below_desired():
    """A partially-available deployment (e.g. 1 of 3 pods ready) must fail
    even though `status.availableReplicas` would previously have been a
    non-zero, "healthy" looking value."""
    check = mod.evaluate_operator_state(
        cluster_type="rhoai",
        deployment_exists=True,
        ready_replicas="1",
        desired_replicas="3",
        csv_phases=[],
    )
    assert check["passed"] is False
    assert "ready replicas: 1/3" in check["details"]


def test_operator_check_fails_when_deployment_exists_and_unready_even_with_succeeded_csv():
    """A present-but-unhealthy deployment must not be rescued by a stale
    "Succeeded" CSV phase; the CSV is only consulted when the deployment
    itself doesn't exist."""
    check = mod.evaluate_operator_state(
        cluster_type="rhoai",
        deployment_exists=True,
        ready_replicas="0",
        desired_replicas="1",
        csv_phases=["Succeeded"],
    )
    assert check["passed"] is False
    assert "ready replicas: 0/1" in check["details"]


def test_operator_check_falls_back_to_csv_success_when_deployment_absent():
    check = mod.evaluate_operator_state(
        cluster_type="rhoai",
        deployment_exists=False,
        ready_replicas="",
        desired_replicas="",
        csv_phases=["Pending", "Succeeded"],
    )
    assert check["passed"] is True
    assert "CSV phase Succeeded" in check["details"]


def test_operator_check_fails_when_no_healthy_signal():
    check = mod.evaluate_operator_state(
        cluster_type="odh",
        deployment_exists=False,
        ready_replicas="",
        desired_replicas="",
        csv_phases=["Pending", "Failed"],
    )
    assert check["passed"] is False


def test_operator_check_reports_rhoai_namespace_in_details():
    check = mod.evaluate_operator_state(
        cluster_type="rhoai",
        deployment_exists=False,
        ready_replicas="",
        desired_replicas="",
        csv_phases=["Pending"],
    )
    assert check["passed"] is False
    assert "redhat-ods-operator" in check["details"]


def test_operator_check_reports_odh_namespace_in_details():
    check = mod.evaluate_operator_state(
        cluster_type="odh",
        deployment_exists=False,
        ready_replicas="",
        desired_replicas="",
        csv_phases=["Pending"],
    )
    assert check["passed"] is False
    assert "opendatahub-operator-system" in check["details"]


def test_operator_namespace_for_rhoai_matches_profile():
    assert mod.operator_namespace_for("rhoai") == "redhat-ods-operator"


def test_operator_namespace_for_odh_matches_profile():
    assert mod.operator_namespace_for("odh") == "opendatahub-operator-system"


def test_dsc_ready_check_fails_with_false_conditions():
    check = mod.evaluate_dsc_state(
        phase="NotReady",
        false_conditions=["ModelController", "Dashboard"],
        require_ready=True,
    )
    assert check["passed"] is False
    assert "ModelController" in check["details"]


def test_dsc_ready_check_fails_with_clear_message_when_dsc_absent():
    check = mod.evaluate_dsc_state(
        phase="",
        false_conditions=[],
        require_ready=True,
        exists=False,
    )
    assert check["name"] == "datasciencecluster_ready"
    assert check["passed"] is False
    assert check["details"] == "DataScienceCluster not found"


def test_dsc_ready_check_passes_when_absent_but_not_required():
    check = mod.evaluate_dsc_state(
        phase="",
        false_conditions=[],
        require_ready=False,
        exists=False,
    )
    assert check["passed"] is True


def test_kserve_check_passes_when_ready_replicas_meet_desired():
    check = mod.evaluate_kserve_state(
        ready_replicas="1", desired_replicas="1", require_kserve=True
    )
    assert check["passed"] is True
    assert "1/1" in check["details"]


def test_kserve_check_fails_when_ready_replicas_below_desired():
    check = mod.evaluate_kserve_state(
        ready_replicas="0", desired_replicas="1", require_kserve=True
    )
    assert check["passed"] is False
    assert "0/1" in check["details"]


def test_kserve_check_fails_when_deployment_missing_replica_status():
    check = mod.evaluate_kserve_state(
        ready_replicas="", desired_replicas="", require_kserve=True
    )
    assert check["passed"] is False


def test_kserve_check_fails_with_clear_message_when_deployment_absent():
    check = mod.evaluate_kserve_state(
        ready_replicas="",
        desired_replicas="",
        require_kserve=True,
        exists=False,
    )
    assert check["name"] == "kserve_controller"
    assert check["passed"] is False
    assert check["details"] == "KServe controller deployment not found"


def test_kserve_check_passes_when_absent_but_not_required():
    check = mod.evaluate_kserve_state(
        ready_replicas="",
        desired_replicas="",
        require_kserve=False,
        exists=False,
    )
    assert check["passed"] is True


def test_build_summary_reports_overall_failure():
    checks = [
        {"name": "operator_health", "passed": True, "details": "Operator healthy"},
        {
            "name": "datasciencecluster_ready",
            "passed": False,
            "details": "DataScienceCluster phase: NotReady",
        },
    ]
    summary = mod.build_summary("rhoai2", checks)
    assert summary["passed"] is False
    assert summary["cluster_profile"] == "rhoai2"


def test_write_outputs_creates_json_and_markdown(tmp_path):
    summary = mod.build_summary(
        "rhoai2",
        [{"name": "operator_health", "passed": True, "details": "Operator healthy"}],
    )
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    mod.write_outputs(summary, json_path, md_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert "QG2 Platform Readiness" in md_path.read_text(encoding="utf-8")


def _fake_operator_deployment_ready(ready="1", exists=True):
    """Build a fake `run_oc_optional` that reports the operator deployment
    as existing (or absent) with the given readyReplicas value, mirroring
    the real function's `(stdout, exists)` return shape."""

    def fake(*args, **kwargs):
        return ready, exists

    return fake


def test_main_writes_failing_summary_when_oc_errors(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["oc", "get", "datasciencecluster", "-A"],
            output="",
            stderr="forbidden",
        )

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", boom)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False


def test_main_writes_failing_summary_when_oc_times_out(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["oc", "get", "datasciencecluster", "-A"],
            timeout=mod.OC_TIMEOUT_SECONDS,
        )

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", boom)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["checks"] == [
        {
            "name": "oc_command",
            "passed": False,
            "details": "Command timed out after 60s (oc get datasciencecluster -A)",
        }
    ]
    markdown = md_path.read_text(encoding="utf-8")
    assert "oc_command: FAIL — Command timed out after 60s (oc get datasciencecluster -A)" in markdown


def test_main_writes_passing_summary_on_happy_path(monkeypatch, tmp_path):
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "my-dsc",  # datasciencecluster names (existence probe)
            "Ready",  # datasciencecluster phase
            "",  # false conditions
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "1",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc(*args, **kwargs):
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True


def test_main_skips_disabled_dsc_and_kserve_probes(monkeypatch, tmp_path):
    calls = []
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "",  # datasciencecluster names (should stop existing code from erroring)
            "",  # kserve deployment names (should stop existing code from erroring)
        ]
    )

    def fake_run_oc(*args, **kwargs):
        calls.append(args)
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--require-dsc-ready",
            "false",
            "--require-kserve",
            "false",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 0
    assert calls == [
        (
            "get",
            "deployment",
            "rhods-operator",
            "-n",
            "redhat-ods-operator",
            "-o",
            "jsonpath={.spec.replicas}",
        )
    ]


def test_main_reports_named_dsc_failure_when_dsc_genuinely_absent(
    monkeypatch, tmp_path
):
    """A cluster with zero DataScienceCluster resources must fail with a
    named `datasciencecluster_ready` check, not collapse into a generic
    `oc_command` failure alongside operator/KServe checks that still ran."""
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "",  # datasciencecluster names (existence probe): none found
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "1",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc(*args, **kwargs):
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    check_names = {c["name"] for c in payload["checks"]}
    assert check_names == {
        "operator_health",
        "datasciencecluster_ready",
        "kserve_controller",
    }
    assert "oc_command" not in check_names

    dsc_check = next(
        c for c in payload["checks"] if c["name"] == "datasciencecluster_ready"
    )
    assert dsc_check["passed"] is False
    assert dsc_check["details"] == "DataScienceCluster not found"

    operator_check = next(
        c for c in payload["checks"] if c["name"] == "operator_health"
    )
    assert operator_check["passed"] is True

    kserve_check = next(
        c for c in payload["checks"] if c["name"] == "kserve_controller"
    )
    assert kserve_check["passed"] is True

    markdown = md_path.read_text(encoding="utf-8")
    assert "datasciencecluster_ready: FAIL — DataScienceCluster not found" in markdown


def test_main_still_reports_generic_oc_command_failure_on_real_oc_error(
    monkeypatch, tmp_path
):
    """A genuine oc failure (auth/timeout/RBAC) on the DSC existence probe
    itself must still hard-fail via the generic `oc_command` path, not be
    mistaken for a genuinely-absent DataScienceCluster."""

    def fake_run_oc(*args, check=True, **kwargs):
        if args and args[0] == "get" and "datasciencecluster" in args:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["oc", *args],
                output="",
                stderr="Unable to connect to the server: forbidden",
            )
        return "1"

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    check_names = {c["name"] for c in payload["checks"]}
    assert check_names == {"oc_command"}


def test_main_still_reports_generic_oc_command_failure_on_real_operator_probe_error(
    monkeypatch, tmp_path
):
    """A genuine (non-NotFound) oc failure on the operator deployment probe
    itself must hard-fail via the generic `oc_command` path, not be silently
    treated as "operator deployment absent" and fall through to the CSV
    fallback."""

    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["oc", "get", "deployment", "rhods-operator"],
            output="",
            stderr="Error from server (Forbidden): deployments.apps is forbidden",
        )

    monkeypatch.setattr(mod, "run_oc_optional", boom)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    check_names = {c["name"] for c in payload["checks"]}
    assert check_names == {"oc_command"}


def test_main_queries_rhoai_specific_operator_deployment_and_namespace(
    monkeypatch, tmp_path
):
    optional_calls = []
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "my-dsc",  # datasciencecluster names (existence probe)
            "Ready",  # datasciencecluster phase
            "",  # false conditions
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "1",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc_optional(*args, **kwargs):
        optional_calls.append(args)
        return "1", True

    def fake_run_oc(*args, **kwargs):
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", fake_run_oc_optional)
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    deployment_call = optional_calls[0]
    assert "rhods-operator" in deployment_call
    assert "redhat-ods-operator" in deployment_call


def test_main_queries_odh_specific_operator_deployment_and_namespace(
    monkeypatch, tmp_path
):
    optional_calls = []
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "my-dsc",  # datasciencecluster names (existence probe)
            "Ready",  # datasciencecluster phase
            "",  # false conditions
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "1",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc_optional(*args, **kwargs):
        optional_calls.append(args)
        return "1", True

    def fake_run_oc(*args, **kwargs):
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", fake_run_oc_optional)
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    mod.main(
        [
            "--cluster-profile",
            "odh1",
            "--cluster-type",
            "odh",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    deployment_call = optional_calls[0]
    assert "opendatahub-operator-controller-manager" in deployment_call
    assert "opendatahub-operator-system" in deployment_call


def test_main_deployment_lookup_is_soft_and_does_not_hard_fail_gate(
    monkeypatch, tmp_path
):
    """A NotFound deployment must fall back to the CSV probe, not abort the run."""
    optional_calls = []
    run_oc_calls = []
    values = iter(
        [
            "Succeeded",  # CSV phase fallback
            "my-dsc",  # datasciencecluster names (existence probe)
            "Ready",  # datasciencecluster phase
            "",  # false conditions
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "1",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc_optional(*args, **kwargs):
        optional_calls.append(args)
        return "", False  # operator deployment lookup: NotFound

    def fake_run_oc(*args, check=True, **kwargs):
        run_oc_calls.append((args, check))
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", fake_run_oc_optional)
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 0
    deployment_call_args = optional_calls[0]
    assert "rhods-operator" in deployment_call_args
    csv_call_args, csv_call_check = run_oc_calls[0]
    assert "redhat-ods-operator" in csv_call_args
    assert csv_call_check is True
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    operator_check = next(
        c for c in payload["checks"] if c["name"] == "operator_health"
    )
    assert operator_check["passed"] is True
    assert "redhat-ods-operator" in operator_check["details"]


def test_main_queries_kserve_controller_deployment_with_label_selector(
    monkeypatch, tmp_path
):
    calls = []
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "my-dsc",  # datasciencecluster names (existence probe)
            "Ready",  # datasciencecluster phase
            "",  # false conditions
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "1",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc(*args, **kwargs):
        calls.append(args)
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    kserve_calls = [call for call in calls if "deployment" in call and "-A" in call]
    assert kserve_calls, "expected at least one KServe deployment lookup"
    for call in kserve_calls:
        assert "control-plane=kserve-controller-manager" in call


def test_main_reports_kserve_not_ready_when_replicas_below_desired(
    monkeypatch, tmp_path
):
    values = iter(
        [
            "1",  # operator deployment desired replicas
            "my-dsc",  # datasciencecluster names (existence probe)
            "Ready",  # datasciencecluster phase
            "",  # false conditions
            "kserve-controller-manager",  # kserve deployment names (existence probe)
            "0",  # kserve ready replicas
            "1",  # kserve desired replicas
        ]
    )

    def fake_run_oc(*args, **kwargs):
        return next(values)

    monkeypatch.setattr(mod, "run_oc_optional", _fake_operator_deployment_ready())
    monkeypatch.setattr(mod, "run_oc", fake_run_oc)
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"
    code = mod.main(
        [
            "--cluster-profile",
            "rhoai2",
            "--cluster-type",
            "rhoai",
            "--summary-json",
            str(json_path),
            "--summary-md",
            str(md_path),
        ]
    )
    assert code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    kserve_check = next(
        c for c in payload["checks"] if c["name"] == "kserve_controller"
    )
    assert kserve_check["passed"] is False
    assert kserve_check["details"] == "KServe controller deployment ready replicas: 0/1"


def _fake_subprocess_run_that_fails(
    cmd, *, check, capture_output, text, encoding, errors, timeout
):
    if check:
        raise subprocess.CalledProcessError(
            returncode=1, cmd=cmd, output="", stderr="not found"
        )
    return subprocess.CompletedProcess(
        args=cmd, returncode=1, stdout="", stderr="not found"
    )


def test_run_oc_returns_empty_string_on_nonzero_exit_when_check_false(monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run", _fake_subprocess_run_that_fails)
    assert mod.run_oc("get", "deployment", "missing", check=False) == ""


def test_run_oc_raises_on_nonzero_exit_when_check_true(monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run", _fake_subprocess_run_that_fails)
    with pytest.raises(subprocess.CalledProcessError):
        mod.run_oc("get", "deployment", "missing")


def test_run_oc_uses_utf8_replacement_when_decoding_output(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok\n", stderr=""
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.run_oc("get", "deployment", "rhods-operator") == "ok"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def _fake_subprocess_run_notfound(
    cmd, *, capture_output, text, encoding, errors, timeout
):
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=1,
        stdout="",
        stderr='Error from server (NotFound): deployments.apps "rhods-operator" not found\n',
    )


def _fake_subprocess_run_forbidden(
    cmd, *, capture_output, text, encoding, errors, timeout
):
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=1,
        stdout="",
        stderr="Error from server (Forbidden): deployments.apps is forbidden\n",
    )


def test_run_oc_optional_returns_absent_on_server_notfound(monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run", _fake_subprocess_run_notfound)
    stdout, exists = mod.run_oc_optional(
        "get", "deployment", "rhods-operator", "-n", "redhat-ods-operator"
    )
    assert exists is False
    assert stdout == ""


def test_run_oc_optional_raises_on_real_error_instead_of_treating_as_absent(
    monkeypatch,
):
    """A Forbidden/RBAC error must not be silently treated as "resource
    absent" — it must propagate so the gate hard-fails instead of falling
    back to the CSV probe under a misleading "operator not installed"
    interpretation."""
    monkeypatch.setattr(mod.subprocess, "run", _fake_subprocess_run_forbidden)
    with pytest.raises(subprocess.CalledProcessError):
        mod.run_oc_optional(
            "get", "deployment", "rhods-operator", "-n", "redhat-ods-operator"
        )


def test_run_oc_optional_returns_exists_true_on_success(monkeypatch):
    def fake_run(cmd, *, capture_output, text, encoding, errors, timeout):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="1\n", stderr=""
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    stdout, exists = mod.run_oc_optional(
        "get", "deployment", "rhods-operator", "-n", "redhat-ods-operator"
    )
    assert exists is True
    assert stdout == "1"


def test_run_oc_optional_uses_utf8_replacement_when_decoding_output(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="1\n", stderr=""
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    stdout, exists = mod.run_oc_optional(
        "get", "deployment", "rhods-operator", "-n", "redhat-ods-operator"
    )
    assert exists is True
    assert stdout == "1"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
