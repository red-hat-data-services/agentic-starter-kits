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


def test_qg1_job_uses_qg1_gate_action():
    # Cluster setup, service-account assumption, checker execution, and
    # results upload are delegated to the qg1-gate composite action (shared
    # with the standalone qg1-cluster-readiness.yml workflow) rather than
    # duplicated inline here. The gate action's own service-account choice
    # (qg1-readiness) is asserted in test_qg1_workflow_contract.py.
    jobs = _load_jobs()
    uses_values = [step.get("uses", "") for step in jobs["qg1"]["steps"]]
    assert "./.github/actions/qg1-gate" in uses_values


def test_qg2_job_uses_qg2_gate_action():
    # See test_qg1_job_uses_qg1_gate_action — same reasoning for QG2. The
    # gate action's service-account choice (qg2-readiness) is asserted in
    # test_qg2_workflow_contract.py.
    jobs = _load_jobs()
    uses_values = [step.get("uses", "") for step in jobs["qg2"]["steps"]]
    assert "./.github/actions/qg2-gate" in uses_values


def test_job_order_places_qg1_and_qg2_before_qg4():
    jobs = _load_jobs()
    job_order = list(jobs.keys())
    assert job_order.index("qg1") < job_order.index("qg4")
    assert job_order.index("qg2") < job_order.index("qg4")


# Exact-text assertions on every `if` condition the DAG simulator
# (test_orchestrator_dag_simulation.py) hardcodes its propagation logic
# against. That simulator does NOT parse these strings — it encodes their
# meaning directly. If a future edit changes any of these conditions, the
# corresponding exact-match assertion below fails, forcing the simulator to
# be reviewed and updated in step rather than silently drifting out of sync.


def test_qg1_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert (
        jobs["qg1"]["if"]
        == "github.repository == 'red-hat-data-services/agentic-starter-kits'"
    )


def test_qg2_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert jobs["qg2"]["if"] == (
        "needs.qg1.result == 'success' && "
        "github.repository == 'red-hat-data-services/agentic-starter-kits'"
    )


def test_verify_cluster_connection_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert jobs["verify-cluster-connection"]["if"] == (
        "always() && github.repository == 'red-hat-data-services/agentic-starter-kits' "
        "&& needs.qg1.result == 'success' && needs.qg2.result == 'success'"
    )


def test_qg4_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert (
        jobs["qg4"]["if"]
        == "github.repository == 'red-hat-data-services/agentic-starter-kits'"
    )


def test_collect_qg4_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert jobs["collect-qg4"]["if"] == (
        "always() && github.repository == 'red-hat-data-services/agentic-starter-kits'"
    )


def test_qg7_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert jobs["qg7"]["if"] == (
        "always() && github.repository == 'red-hat-data-services/agentic-starter-kits' "
        "&& needs.collect-qg4.result == 'success' "
        "&& needs.collect-qg4.outputs.has_passing == 'true'"
    )


def test_notify_slack_if_condition_matches_simulator_assumption():
    jobs = _load_jobs()
    assert jobs["notify-slack"]["if"] == (
        "!cancelled() && github.repository == 'red-hat-data-services/agentic-starter-kits' "
        "&& (github.event_name != 'workflow_dispatch' || github.ref_name == 'main')"
    )
