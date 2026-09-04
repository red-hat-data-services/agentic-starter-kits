"""Simulates the quality-gates-pipeline.yml job DAG to verify failure/skip
propagation end-to-end, instead of just asserting condition strings.

This complements test_orchestrator_contract.py: the contract tests assert
*that* certain substrings appear in `needs`/`if`, while these tests assert
*what actually happens* to every job's result under different upstream
outcomes, matching GitHub Actions' own evaluation semantics (including the
implicit `success()` AND-ing applied to any custom `if` that doesn't use a
status-check function).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "quality-gates-pipeline.yml"

_STATUS_FNS = ("always()", "success()", "failure()", "cancelled()")
_GITHUB_CONTEXT_RE = re.compile(r"github\.[\w.]+\s*(?:==|!=)\s*'[^']*'")
_NEEDS_RESULT_RE = re.compile(r"needs\.([\w-]+)\.result\s*==\s*'([a-zA-Z_]+)'")
_NEEDS_OUTPUT_RE = re.compile(r"needs\.([\w-]+)\.outputs\.([\w-]+)\s*==\s*'([^']*)'")


def _load_jobs() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return workflow["jobs"]


def _needs_list(job: dict) -> list[str]:
    needs = job.get("needs", [])
    if isinstance(needs, str):
        return [needs]
    return list(needs)


def _evaluate_condition(
    cond: str | None, needs_results: dict[str, str], *, has_passing: bool
) -> bool:
    implicit_success = all(r == "success" for r in needs_results.values())

    if cond is None:
        return implicit_success

    has_status_fn = any(fn in cond for fn in _STATUS_FNS)

    expr = _GITHUB_CONTEXT_RE.sub("True", cond)
    expr = _NEEDS_RESULT_RE.sub(
        lambda m: str(needs_results.get(m.group(1)) == m.group(2)), expr
    )
    expr = _NEEDS_OUTPUT_RE.sub(
        lambda m: str(has_passing) if m.group(2) == "has_passing" else "False", expr
    )
    expr = expr.replace("always()", "True")
    expr = expr.replace(
        "failure()", str(any(r == "failure" for r in needs_results.values()))
    )
    expr = expr.replace("success()", str(implicit_success))
    expr = expr.replace("cancelled()", "False")
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)

    explicit_result = bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307

    if has_status_fn:
        return explicit_result
    return implicit_success and explicit_result


def simulate_pipeline(
    job_outcomes: dict[str, str] | None = None, *, has_passing: bool = True
) -> dict[str, str]:
    """Return {job_name: 'success' | 'failure' | 'skipped'} for every job.

    `job_outcomes` forces the result of a job *if it runs* (default
    'success' when unspecified). Jobs whose `if` evaluates to false are
    recorded as 'skipped', mirroring `needs.<job>.result` downstream.
    """
    job_outcomes = job_outcomes or {}
    jobs = _load_jobs()
    results: dict[str, str] = {}
    for name, job in jobs.items():
        needs_results = {n: results[n] for n in _needs_list(job)}
        # collect-qg4's has_passing output can only be true if qg4 actually
        # ran (produced outcome artifacts); a fully skipped qg4 means no
        # artifacts, so the real build-pass-list script forces has_passing
        # to false regardless of what the caller requested.
        effective_has_passing = has_passing and results.get("qg4") not in (
            None,
            "skipped",
        )
        runs = _evaluate_condition(
            job.get("if"), needs_results, has_passing=effective_has_passing
        )
        results[name] = job_outcomes.get(name, "success") if runs else "skipped"
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


def test_notify_slack_runs_even_when_everything_upstream_is_skipped():
    results = simulate_pipeline({"qg1": "failure"})
    assert all(
        results[j] == "skipped"
        for j in ("qg2", "verify-cluster-connection", "qg4", "qg7")
    )
    assert results["notify-slack"] == "success"
