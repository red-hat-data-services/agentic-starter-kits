from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "run-qg1" / "action.yml"
ASSUME_ACTION_PATH = (
    REPO_ROOT / ".github" / "actions" / "assume-service-account" / "action.yml"
)
GATE_ACTION_PATH = REPO_ROOT / ".github" / "actions" / "qg1-gate" / "action.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "qg1-cluster-readiness.yml"
RBAC_MANIFEST_PATH = REPO_ROOT / ".github" / "cluster" / "qg1-readiness-rbac.yaml"


def _resolve_require_gpu(env_overrides: dict[str, str], tmp_path: Path) -> str:
    """Execute the workflow's real "Resolve QG1 inputs" bash step in isolation.

    Reads the run: script straight out of the workflow YAML so a future edit to
    the require_gpu resolution logic is exercised by this test automatically.
    """
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    resolve_step = next(
        step for step in workflow["jobs"]["qg1"]["steps"] if step.get("id") == "resolve"
    )

    output_path = tmp_path / "github_output"
    output_path.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.pop("DISPATCH_REQUIRE_GPU", None)
    env.pop("VARS_REQUIRE_GPU", None)
    env["GITHUB_OUTPUT"] = str(output_path)
    env.update(env_overrides)

    subprocess.run(
        ["bash", "-c", resolve_step["run"]],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    outputs = dict(
        line.split("=", 1)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line
    )
    return outputs["require-gpu"]


def test_run_qg1_action_exists():
    assert ACTION_PATH.is_file()


def test_assume_qg1_service_account_action_exists():
    assert ASSUME_ACTION_PATH.is_file()


def test_run_qg1_action_declares_expected_inputs():
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    assert action["name"] == "Run QG1 Cluster Readiness"
    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert set(inputs) == {
        "cluster-profile",
        "require-gpu",
        "required-namespaces",
        "summary-json-path",
        "summary-md-path",
    }


def test_assume_qg1_service_account_action_declares_expected_inputs():
    action = yaml.safe_load(ASSUME_ACTION_PATH.read_text(encoding="utf-8"))
    assert action["name"] == "Assume Service Account"
    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert set(inputs) == {"service-account", "namespace"}
    assert inputs["service-account"]["default"] == "qg1-readiness"
    assert inputs["namespace"]["default"] == "ci-testing"


def test_run_qg1_action_invokes_checker_script():
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    bash_steps = [
        step for step in action["runs"]["steps"] if step.get("shell") == "bash"
    ]
    assert any(
        ".github/scripts/qg1_cluster_readiness.py" in step.get("run", "")
        for step in bash_steps
    )
    assert any("GITHUB_STEP_SUMMARY" in step.get("run", "") for step in bash_steps)


def test_assume_qg1_service_account_action_mints_token_and_relogs():
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


def test_run_qg1_action_passes_inputs_via_env_not_inline_interpolation():
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    bash_steps = [
        step for step in action["runs"]["steps"] if step.get("shell") == "bash"
    ]
    assert bash_steps, "expected at least one bash step in run-qg1 action"
    for step in bash_steps:
        assert "${{ inputs." not in step.get("run", ""), (
            f"step {step.get('name')!r} interpolates inputs directly in run: "
            "body; pass via env: instead"
        )


def test_qg1_workflow_exists():
    assert WORKFLOW_PATH.is_file()


def test_qg1_workflow_uses_qg1_gate_action():
    # Cluster setup, service-account assumption, checker execution, and
    # results upload live in the qg1-gate composite action (shared with
    # quality-gates-pipeline.yml's qg1 job) rather than being duplicated
    # inline in this workflow. See test_qg1_gate_action_* below for
    # assertions on the gate action's internal composition.
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["name"] == "QG1: Cluster Readiness"
    uses_values = [step.get("uses", "") for step in workflow["jobs"]["qg1"]["steps"]]
    assert "./.github/actions/qg1-gate" in uses_values


def test_run_qg1_gate_step_consumes_resolved_require_gpu_output():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    gate_step = next(
        step
        for step in workflow["jobs"]["qg1"]["steps"]
        if step.get("uses") == "./.github/actions/qg1-gate"
    )
    assert (
        gate_step["with"]["require-gpu"] == "${{ steps.resolve.outputs.require-gpu }}"
    )


def test_qg1_gate_action_exists():
    assert GATE_ACTION_PATH.is_file()


def test_qg1_gate_action_declares_expected_inputs():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "oc-token",
        "cluster-api-url",
        "cluster-profile",
        "require-gpu",
        "required-namespaces",
    }


def test_qg1_gate_action_composes_setup_assume_run_upload_logout_in_order():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    uses_values = [
        step.get("uses", "") for step in action["runs"]["steps"] if "uses" in step
    ]
    setup_idx = uses_values.index("./.github/actions/setup-cluster")
    assume_idx = uses_values.index("./.github/actions/assume-service-account")
    run_idx = uses_values.index("./.github/actions/run-qg1")
    assert setup_idx < assume_idx < run_idx


def test_qg1_gate_action_assumes_qg1_readiness_service_account():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    assume_step = next(
        step
        for step in action["runs"]["steps"]
        if step.get("uses") == "./.github/actions/assume-service-account"
    )
    assert assume_step["with"]["service-account"] == "qg1-readiness"


def test_qg1_gate_action_forwards_inputs_to_run_qg1():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    run_step = next(
        step
        for step in action["runs"]["steps"]
        if step.get("uses") == "./.github/actions/run-qg1"
    )
    assert run_step["with"]["cluster-profile"] == "${{ inputs.cluster-profile }}"
    assert run_step["with"]["require-gpu"] == "${{ inputs.require-gpu }}"
    assert (
        run_step["with"]["required-namespaces"] == "${{ inputs.required-namespaces }}"
    )


def test_qg1_gate_action_upload_and_logout_run_even_on_failure():
    action = yaml.safe_load(GATE_ACTION_PATH.read_text(encoding="utf-8"))
    steps_by_name = {step["name"]: step for step in action["runs"]["steps"]}
    assert steps_by_name["Upload QG1 results"]["if"] == "always()"
    logout_step = steps_by_name["Logout"]
    assert logout_step["if"] == "always()"
    # Composite action run: steps require an explicit shell (no ambient
    # default the way top-level workflow steps have).
    assert logout_step["shell"] == "bash"


def test_qg1_workflow_is_dispatch_only():
    # No schedule trigger: the orchestrator (quality-gates-pipeline.yml) owns
    # the nightly cadence and already runs qg1 as a job. A standalone
    # schedule here would fire a second, duplicate Slack notification for
    # the same failure (see agent-deployment-test.yaml, which dropped its
    # schedule trigger for the same reason once QG4 moved into the
    # orchestrator). workflow_dispatch is kept for ad-hoc manual runs.
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert set(triggers) == {"workflow_dispatch"}


def test_qg1_rbac_manifest_exists():
    assert RBAC_MANIFEST_PATH.is_file()


def test_qg1_rbac_manifest_declares_minimal_read_only_resources():
    docs = list(yaml.safe_load_all(RBAC_MANIFEST_PATH.read_text(encoding="utf-8")))
    service_account = next(doc for doc in docs if doc["kind"] == "ServiceAccount")
    cluster_role = next(doc for doc in docs if doc["kind"] == "ClusterRole")
    cluster_role_binding = next(
        doc for doc in docs if doc["kind"] == "ClusterRoleBinding"
    )

    assert service_account["metadata"] == {
        "name": "qg1-readiness",
        "namespace": "ci-testing",
    }
    assert cluster_role["metadata"]["name"] == "qg1-readiness-reader"
    assert cluster_role_binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "qg1-readiness-reader",
    }
    assert cluster_role_binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": "qg1-readiness",
            "namespace": "ci-testing",
        }
    ]

    rule_map = {
        (tuple(rule["apiGroups"]), tuple(rule["resources"])): set(rule["verbs"])
        for rule in cluster_role["rules"]
    }
    assert len(rule_map) == 3
    assert rule_map[(("config.openshift.io",), ("clusterversions",))] == {
        "get",
        "list",
    }
    assert rule_map[(("",), ("nodes",))] == {"get", "list"}
    assert rule_map[(("",), ("namespaces",))] == {"get", "list"}


def test_resolve_require_gpu_uses_dispatch_input_on_manual_run(tmp_path):
    require_gpu = _resolve_require_gpu(
        {
            "EVENT_NAME": "workflow_dispatch",
            "DISPATCH_REQUIRE_GPU": "false",
            "VARS_REQUIRE_GPU": "true",
        },
        tmp_path,
    )
    assert require_gpu == "false"


def test_resolve_require_gpu_falls_back_to_repo_variable_on_schedule(tmp_path):
    require_gpu = _resolve_require_gpu(
        {
            "EVENT_NAME": "schedule",
            "VARS_REQUIRE_GPU": "false",
        },
        tmp_path,
    )
    assert require_gpu == "false"


def test_resolve_require_gpu_defaults_to_true_when_repo_variable_unset(tmp_path):
    require_gpu = _resolve_require_gpu({"EVENT_NAME": "schedule"}, tmp_path)
    assert require_gpu == "true"
