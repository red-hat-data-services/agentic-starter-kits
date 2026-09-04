from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "quality-gates-pipeline.yml"


def _load_jobs() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return workflow["jobs"]


def test_orchestrator_workflow_exists():
    assert WORKFLOW_PATH.is_file()


def test_qg1_has_no_upstream_dependency():
    jobs = _load_jobs()
    assert "needs" not in jobs["qg1"]


def test_qg2_runs_sequentially_after_qg1():
    jobs = _load_jobs()
    assert jobs["qg2"]["needs"] == "qg1"


def test_qg2_only_runs_if_qg1_succeeds():
    # QG1 and QG2 must run in sequence, and QG2 must not start unless QG1
    # succeeded: platform-readiness checks assume a reachable,
    # GPU/namespace-verified cluster.
    jobs = _load_jobs()
    qg2_if = jobs["qg2"]["if"]
    assert "needs.qg1.result == 'success'" in qg2_if
    assert "always()" not in qg2_if


def test_verify_cluster_connection_requires_both_qg1_and_qg2_success():
    jobs = _load_jobs()
    verify_job = jobs["verify-cluster-connection"]
    assert set(verify_job["needs"]) == {"qg1", "qg2"}
    verify_if = verify_job["if"]
    assert "needs.qg1.result == 'success'" in verify_if
    assert "needs.qg2.result == 'success'" in verify_if


def test_qg4_transitively_depends_on_verify_cluster_connection():
    jobs = _load_jobs()
    assert jobs["qg4"]["needs"] == "verify-cluster-connection"


def test_notify_slack_depends_on_all_upstream_gates():
    jobs = _load_jobs()
    notify_needs = jobs["notify-slack"]["needs"]
    assert set(notify_needs) == {
        "qg1",
        "qg2",
        "verify-cluster-connection",
        "qg4",
        "collect-qg4",
        "qg7",
    }


def test_qg1_assumes_explicit_dedicated_service_account():
    # QG1 should declare its service account explicitly rather than relying
    # on the assume-service-account action's implicit default, matching QG2's
    # explicit pattern.
    jobs = _load_jobs()
    assume_step = next(
        step
        for step in jobs["qg1"]["steps"]
        if step.get("uses") == "./.github/actions/assume-service-account"
    )
    assert assume_step["with"]["service-account"] == "qg1-readiness"


def test_qg2_assumes_explicit_dedicated_service_account():
    jobs = _load_jobs()
    assume_step = next(
        step
        for step in jobs["qg2"]["steps"]
        if step.get("uses") == "./.github/actions/assume-service-account"
    )
    assert assume_step["with"]["service-account"] == "qg2-readiness"


def test_job_order_places_qg1_and_qg2_before_qg4():
    jobs = _load_jobs()
    job_order = list(jobs.keys())
    assert job_order.index("qg1") < job_order.index("qg4")
    assert job_order.index("qg2") < job_order.index("qg4")
