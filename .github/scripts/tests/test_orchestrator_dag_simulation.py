"""Explicit failure/skip propagation scenarios for quality-gates-pipeline.yml.

This intentionally does NOT parse or evaluate GitHub Actions `if:` expression
syntax generically — an earlier version of this file did that with a
regex+eval interpreter, which only handled a narrow subset of Actions
grammar, silently hardcoded `cancelled()` to false, and could raise on
perfectly valid expressions it didn't anticipate (e.g. `!=` comparisons).
That created false confidence: tests passed without actually matching
Actions semantics.

Instead, `simulate_pipeline()` below hardcodes this pipeline's specific,
known propagation logic as plain Python conditionals, with each branch
commented against the exact job it mirrors. test_orchestrator_contract.py
asserts the real `if:` text for each of these jobs matches character-for-
character — if someone changes a condition in the workflow, that exact-match
assertion fails and forces this file to be reviewed and updated too, rather
than letting the two silently drift apart.
"""

from __future__ import annotations


def simulate_pipeline(
    job_outcomes: dict[str, str] | None = None, *, has_passing: bool = True
) -> dict[str, str]:
    """Return {job_name: 'success' | 'failure' | 'skipped'} for every job.

    `job_outcomes` forces the result of a job *if it runs* (default
    'success' when unspecified). `has_passing` simulates collect-qg4's
    `has_passing` output when qg4 actually ran; it has no effect if qg4 was
    skipped, since a fully skipped qg4 produces no outcome artifacts and the
    real build-pass-list script forces has_passing to false in that case.
    """
    job_outcomes = job_outcomes or {}
    results: dict[str, str] = {}

    def run(name: str, default: str = "success") -> None:
        results[name] = job_outcomes.get(name, default)

    def skip(name: str) -> None:
        results[name] = "skipped"

    # qg1: if: github.repository == '...' (no needs) -> always attempted.
    run("qg1")

    # qg2: if: needs.qg1.result == 'success' && github.repository == '...'
    if results["qg1"] == "success":
        run("qg2")
    else:
        skip("qg2")

    # verify-cluster-connection: if: always() && github.repository == '...'
    # && needs.qg1.result == 'success' && needs.qg2.result == 'success'
    if results["qg1"] == "success" and results["qg2"] == "success":
        run("verify-cluster-connection")
    else:
        skip("verify-cluster-connection")

    # qg4: if: github.repository == '...' — no status-check function, so
    # Actions implicitly ANDs this with success() over `needs`.
    if results["verify-cluster-connection"] == "success":
        run("qg4")
    else:
        skip("qg4")

    # collect-qg4: if: always() && github.repository == '...' — no
    # needs.qg4.result check at all, so it runs unconditionally even when
    # qg4 was fully skipped.
    run("collect-qg4")

    # qg7: if: always() && github.repository == '...' &&
    # needs.collect-qg4.result == 'success' &&
    # needs.collect-qg4.outputs.has_passing == 'true'
    qg4_produced_artifacts = results["qg4"] != "skipped"
    effective_has_passing = has_passing and qg4_produced_artifacts
    if results["collect-qg4"] == "success" and effective_has_passing:
        run("qg7")
    else:
        skip("qg7")

    # notify-slack: if: !cancelled() && github.repository == '...' &&
    # (github.event_name != 'workflow_dispatch' || github.ref_name == 'main')
    # Always runs (never cancelled in these scenarios), regardless of
    # upstream results — that's what lets it report a QG1/QG2 failure.
    run("notify-slack")

    return results


def test_happy_path_all_gates_run_and_pass():
    results = simulate_pipeline()
    assert results == {
        "qg1": "success",
        "qg2": "success",
        "verify-cluster-connection": "success",
        "qg4": "success",
        "collect-qg4": "success",
        "qg7": "success",
        "notify-slack": "success",
    }


def test_qg1_failure_blocks_qg2_and_all_downstream_gates():
    results = simulate_pipeline({"qg1": "failure"})
    assert results["qg1"] == "failure"
    assert results["qg2"] == "skipped"
    assert results["verify-cluster-connection"] == "skipped"
    assert results["qg4"] == "skipped"
    assert results["qg7"] == "skipped"


def test_qg1_failure_still_lets_notify_slack_report():
    results = simulate_pipeline({"qg1": "failure"})
    assert results["notify-slack"] == "success"


def test_qg2_only_runs_when_qg1_succeeds():
    results = simulate_pipeline({"qg1": "failure"})
    assert results["qg2"] == "skipped"


def test_qg2_failure_blocks_qg4_and_qg7_but_qg1_result_still_stands():
    results = simulate_pipeline({"qg2": "failure"})
    assert results["qg1"] == "success"
    assert results["qg2"] == "failure"
    assert results["verify-cluster-connection"] == "skipped"
    assert results["qg4"] == "skipped"
    assert results["qg7"] == "skipped"


def test_qg2_failure_still_lets_notify_slack_report():
    results = simulate_pipeline({"qg2": "failure"})
    assert results["notify-slack"] == "success"


def test_qg4_failure_does_not_skip_collect_qg4_or_qg7():
    # collect-qg4 uses always(): it must still build a pass-list even when
    # some/all QG4 matrix legs failed.
    results = simulate_pipeline({"qg4": "failure"})
    assert results["collect-qg4"] == "success"
    assert results["qg7"] == "success"


def test_qg7_skipped_when_no_agents_pass_qg4():
    results = simulate_pipeline(has_passing=False)
    assert results["collect-qg4"] == "success"
    assert results["qg7"] == "skipped"


def test_qg7_skipped_when_qg4_fully_skipped_even_if_has_passing_requested():
    # Guards the has_passing/qg4-skip interaction: a caller can't force qg7
    # to run by passing has_passing=True if qg4 never actually executed.
    results = simulate_pipeline({"qg1": "failure"}, has_passing=True)
    assert results["qg4"] == "skipped"
    assert results["qg7"] == "skipped"


def test_notify_slack_runs_even_when_everything_upstream_is_skipped():
    results = simulate_pipeline({"qg1": "failure"})
    assert all(
        results[j] == "skipped"
        for j in ("qg2", "verify-cluster-connection", "qg4", "qg7")
    )
    assert results["notify-slack"] == "success"
