from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "run-qg2" / "action.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "qg2-platform-readiness.yml"


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


def test_qg2_workflow_uses_shared_setup_and_qg2_action():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["name"] == "QG2: Platform Readiness"
    qg2_job = workflow["jobs"]["qg2"]
    steps = qg2_job["steps"]
    uses_values = [step.get("uses", "") for step in steps]
    assert "./.github/actions/setup-cluster" in uses_values
    assert "./.github/actions/run-qg2" in uses_values


def test_run_qg2_step_consumes_resolved_require_dsc_ready_output():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    run_qg2_step = next(
        step
        for step in workflow["jobs"]["qg2"]["steps"]
        if step.get("uses") == "./.github/actions/run-qg2"
    )
    assert (
        run_qg2_step["with"]["require-dsc-ready"]
        == "${{ steps.resolve.outputs.require-dsc-ready }}"
    )


def test_run_qg2_step_consumes_resolved_require_kserve_output():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    run_qg2_step = next(
        step
        for step in workflow["jobs"]["qg2"]["steps"]
        if step.get("uses") == "./.github/actions/run-qg2"
    )
    assert (
        run_qg2_step["with"]["require-kserve"]
        == "${{ steps.resolve.outputs.require-kserve }}"
    )


def test_qg2_workflow_includes_dispatch_and_schedule():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers


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
