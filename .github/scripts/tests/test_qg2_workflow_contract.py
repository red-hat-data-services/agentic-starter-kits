from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "run-qg2" / "action.yml"
ASSUME_ACTION_PATH = (
    REPO_ROOT / ".github" / "actions" / "assume-service-account" / "action.yml"
)
GATE_ACTION_PATH = REPO_ROOT / ".github" / "actions" / "qg2-gate" / "action.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "qg2-platform-readiness.yml"
RBAC_MANIFEST_PATH = REPO_ROOT / ".github" / "cluster" / "qg2-readiness-rbac.yaml"


def _resolve_qg2_inputs(
    env_overrides: dict[str, str], tmp_path: Path
) -> dict[str, str]:
    """Execute the workflow's real "Resolve QG2 inputs" bash step in isolation.

    Reads the run: script straight out of the workflow YAML so a future edit to
    the require-dsc-ready/require-kserve resolution logic is exercised by this
    test automatically.
    """
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    resolve_step = next(
        step for step in workflow["jobs"]["qg2"]["steps"] if step.get("id") == "resolve"
    )

    output_path = tmp_path / "github_output"
    output_path.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.pop("DISPATCH_REQUIRE_DSC_READY", None)
    env.pop("DISPATCH_REQUIRE_KSERVE", None)
    env.pop("VARS_REQUIRE_DSC_READY", None)
    env.pop("VARS_REQUIRE_KSERVE", None)
    env["GITHUB_OUTPUT"] = str(output_path)
    env.update(env_overrides)

    subprocess.run(
        ["bash", "-c", resolve_step["run"]],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    return dict(
        line.split("=", 1)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line
    )


def test_run_qg2_action_exists():
    assert ACTION_PATH.is_file()


def test_assume_qg2_service_account_action_exists():
    assert ASSUME_ACTION_PATH.is_file()


def test_run_qg2_action_declares_expected_inputs():
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    assert action["name"] == "Run QG2 Platform Readiness"
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "cluster-profile",
        "cluster-type",
        "require-dsc-ready",
        "require-kserve",
        "summary-json-path",
        "summary-md-path",
    }


def test_assume_qg2_service_account_action_declares_expected_inputs():
    action = yaml.safe_load(ASSUME_ACTION_PATH.read_text(encoding="utf-8"))
    assert action["name"] == "Assume Service Account"
    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert set(inputs) == {"service-account", "namespace"}
    assert inputs["service-account"]["default"] == "qg1-readiness"
    assert inputs["namespace"]["default"] == "ci-testing"


def test_run_qg2_action_invokes_checker_script():
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    bash_steps = [
        step for step in action["runs"]["steps"] if step.get("shell") == "bash"
    ]
    assert any(
        ".github/scripts/qg2_platform_readiness.py" in step.get("run", "")
        for step in bash_steps
    )
    assert any("GITHUB_STEP_SUMMARY" in step.get("run", "") for step in bash_steps)


def test_assume_qg2_service_account_action_mints_token_and_relogs():
    action = yaml.safe_load(ASSUME_ACTION_PATH.read_text(encoding="utf-8"))
    bash_steps = [
        step for step in action["runs"]["steps"] if step.get("shell") == "bash"
    ]
    assert any("oc create token" in step.get("run", "") for step in bash_steps)
    assert any("--duration=20m" in step.get("run", "") for step in bash_steps)
    assert any("oc whoami --show-server" in step.get("run", "") for step in bash_steps)
    assert any("oc login" in step.get("run", "") for step in bash_steps)
    assert any(
        "expected_identity=" in step.get("run", "")
        and "actual_identity=" in step.get("run", "")
        for step in bash_steps
    )


def test_run_qg2_action_passes_inputs_via_env_not_inline_interpolation():
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    bash_steps = [
        step for step in action["runs"]["steps"] if step.get("shell") == "bash"
    ]
    assert bash_steps, "expected at least one bash step in run-qg2 action"
    for step in bash_steps:
        assert "${{ inputs." not in step.get("run", ""), (
            f"step {step.get('name')!r} interpolates inputs directly in run: "
            "body; pass via env: instead"
        )


def test_qg2_workflow_exists():
    assert WORKFLOW_PATH.is_file()


def test_qg2_workflow_uses_qg2_gate_action():
    # Cluster setup, service-account assumption, checker execution, and
    # results upload live in the qg2-gate composite action (shared with
    # quality-gates-pipeline.yml's qg2 job) rather than being duplicated
    # inline in this workflow. See test_qg2_gate_action_* below for
    # assertions on the gate action's internal composition.
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["name"] == "QG2: Platform Readiness"
    uses_values = [step.get("uses", "") for step in workflow["jobs"]["qg2"]["steps"]]
    assert "./.github/actions/qg2-gate" in uses_values


def test_run_qg2_gate_step_consumes_resolved_require_dsc_ready_output():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    gate_step = next(
        step
        for step in workflow["jobs"]["qg2"]["steps"]
        if step.get("uses") == "./.github/actions/qg2-gate"
    )
    assert (
        gate_step["with"]["require-dsc-ready"]
        == "${{ steps.resolve.outputs.require-dsc-ready }}"
    )


def test_run_qg2_gate_step_consumes_resolved_require_kserve_output():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    gate_step = next(
        step
        for step in workflow["jobs"]["qg2"]["steps"]
        if step.get("uses") == "./.github/actions/qg2-gate"
    )
    assert (
        gate_step["with"]["require-kserve"]
        == "${{ steps.resolve.outputs.require-kserve }}"
    )


def test_qg2_gate_action_exists():
    assert GATE_ACTION_PATH.is_file()


def test_qg2_gate_action_declares_expected_inputs():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "oc-token",
        "cluster-api-url",
        "cluster-profile",
        "cluster-type",
        "require-dsc-ready",
        "require-kserve",
    }


def test_qg2_gate_action_composes_setup_assume_run_upload_logout_in_order():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    uses_values = [
        step.get("uses", "") for step in action["runs"]["steps"] if "uses" in step
    ]
    setup_idx = uses_values.index("./.github/actions/setup-cluster")
    assume_idx = uses_values.index("./.github/actions/assume-service-account")
    run_idx = uses_values.index("./.github/actions/run-qg2")
    assert setup_idx < assume_idx < run_idx


def test_qg2_gate_action_assumes_qg2_readiness_service_account():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    assume_step = next(
        step
        for step in action["runs"]["steps"]
        if step.get("uses") == "./.github/actions/assume-service-account"
    )
    assert assume_step["with"]["service-account"] == "qg2-readiness"


def test_qg2_gate_action_forwards_inputs_to_run_qg2():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    run_step = next(
        step
        for step in action["runs"]["steps"]
        if step.get("uses") == "./.github/actions/run-qg2"
    )
    assert run_step["with"]["cluster-profile"] == "${{ inputs.cluster-profile }}"
    assert run_step["with"]["cluster-type"] == "${{ inputs.cluster-type }}"
    assert run_step["with"]["require-dsc-ready"] == "${{ inputs.require-dsc-ready }}"
    assert run_step["with"]["require-kserve"] == "${{ inputs.require-kserve }}"


def test_qg2_gate_action_upload_and_logout_run_even_on_failure():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    steps_by_name = {step["name"]: step for step in action["runs"]["steps"]}
    assert steps_by_name["Upload QG2 results"]["if"] == "always()"
    logout_step = steps_by_name["Logout"]
    assert logout_step["if"] == "always()"
    assert logout_step["shell"] == "bash"


def test_qg2_workflow_is_dispatch_only():
    # No schedule trigger: the orchestrator (quality-gates-pipeline.yml) owns
    # the nightly cadence and already runs qg2 as a job. A standalone
    # schedule here would fire a second, duplicate Slack notification for
    # the same failure (see agent-deployment-test.yaml, which dropped its
    # schedule trigger for the same reason once QG4 moved into the
    # orchestrator). workflow_dispatch is kept for ad-hoc manual runs.
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert set(triggers) == {"workflow_dispatch"}


def test_qg2_rbac_manifest_exists():
    assert RBAC_MANIFEST_PATH.is_file()


def test_qg2_rbac_manifest_declares_minimal_read_only_resources():
    docs = list(yaml.safe_load_all(RBAC_MANIFEST_PATH.read_text(encoding="utf-8")))
    service_account = next(doc for doc in docs if doc["kind"] == "ServiceAccount")
    cluster_role = next(doc for doc in docs if doc["kind"] == "ClusterRole")
    cluster_role_binding = next(
        doc for doc in docs if doc["kind"] == "ClusterRoleBinding"
    )

    assert service_account["metadata"] == {
        "name": "qg2-readiness",
        "namespace": "ci-testing",
    }
    assert cluster_role["metadata"]["name"] == "qg2-readiness-reader"
    assert cluster_role_binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "qg2-readiness-reader",
    }
    assert cluster_role_binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": "qg2-readiness",
            "namespace": "ci-testing",
        }
    ]

    rule_map = {
        (tuple(rule["apiGroups"]), tuple(rule["resources"])): set(rule["verbs"])
        for rule in cluster_role["rules"]
    }
    assert len(rule_map) == 3
    assert rule_map[(("apps",), ("deployments",))] == {"get", "list"}
    assert rule_map[(("operators.coreos.com",), ("clusterserviceversions",))] == {
        "get",
        "list",
    }
    assert rule_map[
        (("datasciencecluster.opendatahub.io",), ("datascienceclusters",))
    ] == {"get", "list"}


def test_resolve_qg2_inputs_uses_dispatch_inputs_on_manual_run(tmp_path):
    outputs = _resolve_qg2_inputs(
        {
            "EVENT_NAME": "workflow_dispatch",
            "DISPATCH_REQUIRE_DSC_READY": "false",
            "DISPATCH_REQUIRE_KSERVE": "false",
            "VARS_REQUIRE_DSC_READY": "true",
            "VARS_REQUIRE_KSERVE": "true",
        },
        tmp_path,
    )
    assert outputs["require-dsc-ready"] == "false"
    assert outputs["require-kserve"] == "false"


def test_resolve_qg2_inputs_falls_back_to_repo_variables_on_schedule(tmp_path):
    outputs = _resolve_qg2_inputs(
        {
            "EVENT_NAME": "schedule",
            "VARS_REQUIRE_DSC_READY": "false",
            "VARS_REQUIRE_KSERVE": "false",
        },
        tmp_path,
    )
    assert outputs["require-dsc-ready"] == "false"
    assert outputs["require-kserve"] == "false"


def test_resolve_qg2_inputs_defaults_to_true_when_repo_variables_unset(tmp_path):
    outputs = _resolve_qg2_inputs({"EVENT_NAME": "schedule"}, tmp_path)
    assert outputs["require-dsc-ready"] == "true"
    assert outputs["require-kserve"] == "true"
