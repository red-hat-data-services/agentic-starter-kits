from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

OC_TIMEOUT_SECONDS = 60

# Real per-flavor operator namespace/deployment conventions (see
# red-hat-data-services/rhods-operator docs/OLMDeployment.md and
# docs/troubleshooting.md for RHOAI, and opendatahub-operator's default
# `--operator-namespace` for ODH). Keeping this mapping explicit and used for
# every operator probe (deployment lookup and CSV fallback alike) prevents QG2
# from ever checking the wrong flavor's namespace and misreporting a healthy
# operator as absent, or vice versa.
OPERATOR_PROFILES: dict[str, dict[str, str]] = {
    "rhoai": {
        "namespace": "redhat-ods-operator",
        "deployment": "rhods-operator",
    },
    "odh": {
        "namespace": "opendatahub-operator-system",
        "deployment": "opendatahub-operator-controller-manager",
    },
}

KSERVE_LABEL_SELECTOR = "control-plane=kserve-controller-manager"


def operator_namespace_for(cluster_type: str) -> str:
    return OPERATOR_PROFILES[cluster_type]["namespace"]


def _to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def run_oc(*args: str, timeout: float = OC_TIMEOUT_SECONDS, check: bool = True) -> str:
    result = subprocess.run(
        ["oc", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if not check and result.returncode != 0:
        return ""
    return result.stdout.strip()


def run_oc_optional(
    *args: str, timeout: float = OC_TIMEOUT_SECONDS
) -> tuple[str, bool]:
    """Run `oc <args>` for a single named resource, distinguishing genuine
    absence from every other failure mode.

    A single-named-resource `oc get` (unlike a list/`-A` query) always exits
    non-zero when the resource doesn't exist, so a plain `check=False` call
    can't tell "NotFound" apart from a real auth/RBAC/timeout/connection
    error — both just come back as an empty string. This queries the server
    directly and only treats the server's own `NotFound` response as
    absence; every other non-zero exit re-raises as `CalledProcessError` so
    real oc errors still hard-fail the gate instead of being silently
    misreported as "resource absent".
    """
    result = subprocess.run(
        ["oc", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode == 0:
        return result.stdout.strip(), True
    stderr = result.stderr or ""
    if "NotFound" in stderr:
        return "", False
    raise subprocess.CalledProcessError(
        result.returncode, ["oc", *args], output=result.stdout, stderr=stderr
    )


def evaluate_operator_state(
    *,
    cluster_type: str,
    deployment_exists: bool,
    ready_replicas: str,
    desired_replicas: str,
    csv_phases: list[str],
) -> dict[str, object]:
    namespace = operator_namespace_for(cluster_type)
    if deployment_exists:
        ready = _to_int(ready_replicas)
        desired = _to_int(desired_replicas)
        passed = desired > 0 and ready >= desired
        return {
            "name": "operator_health",
            "passed": passed,
            "details": (
                f"Operator deployment ready replicas: {ready}/{desired} ({namespace})"
            ),
        }
    if any(phase == "Succeeded" for phase in csv_phases):
        return {
            "name": "operator_health",
            "passed": True,
            "details": (
                f"Operator deployment not found in {namespace}; CSV phase Succeeded"
            ),
        }
    return {
        "name": "operator_health",
        "passed": False,
        "details": (
            f"Operator deployment not found in {namespace} and no healthy "
            f"CSV signal. CSV phases: {csv_phases}"
        ),
    }


def evaluate_dsc_state(
    *,
    phase: str,
    false_conditions: list[str],
    require_ready: bool,
    exists: bool = True,
) -> dict[str, object]:
    if not require_ready:
        return {
            "name": "datasciencecluster_ready",
            "passed": True,
            "details": f"DSC readiness requirement disabled (phase: {phase or 'missing'})",
        }
    if not exists:
        return {
            "name": "datasciencecluster_ready",
            "passed": False,
            "details": "DataScienceCluster not found",
        }
    if phase == "Ready":
        return {
            "name": "datasciencecluster_ready",
            "passed": True,
            "details": "DataScienceCluster phase: Ready",
        }
    detail = f"DataScienceCluster phase: {phase or 'missing'}"
    if false_conditions:
        detail += f"; not ready components: {', '.join(false_conditions)}"
    return {
        "name": "datasciencecluster_ready",
        "passed": False,
        "details": detail,
    }


def evaluate_kserve_state(
    *,
    ready_replicas: str,
    desired_replicas: str,
    require_kserve: bool,
    exists: bool = True,
) -> dict[str, object]:
    if not require_kserve:
        return {
            "name": "kserve_controller",
            "passed": True,
            "details": "KServe requirement disabled",
        }
    if not exists:
        return {
            "name": "kserve_controller",
            "passed": False,
            "details": "KServe controller deployment not found",
        }
    ready = _to_int(ready_replicas)
    desired = _to_int(desired_replicas)
    passed = desired > 0 and ready >= desired
    return {
        "name": "kserve_controller",
        "passed": passed,
        "details": f"KServe controller deployment ready replicas: {ready}/{desired}",
    }


def build_summary(
    cluster_profile: str, checks: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "cluster_profile": cluster_profile,
        "passed": all(bool(item["passed"]) for item in checks),
        "checks": checks,
    }


def build_error_summary(
    cluster_profile: str,
    error: subprocess.CalledProcessError | subprocess.TimeoutExpired,
) -> dict[str, object]:
    command = " ".join(error.cmd) if isinstance(error.cmd, list) else str(error.cmd)
    if isinstance(error, subprocess.TimeoutExpired):
        details = f"Command timed out after {error.timeout}s ({command})"
    else:
        stderr = (error.stderr or "").strip()
        details = f"Command failed ({command}): {stderr or 'no stderr output'}"
    return {
        "cluster_profile": cluster_profile,
        "passed": False,
        "checks": [{"name": "oc_command", "passed": False, "details": details}],
    }


def write_outputs(summary: dict[str, object], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# QG2 Platform Readiness",
        "",
        f"- cluster_profile: {summary['cluster_profile']}",
        f"- overall: {'PASS' if summary['passed'] else 'FAIL'}",
        "",
    ]
    for check in summary["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {check['name']}: {status} — {check['details']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster-profile", required=True)
    parser.add_argument("--cluster-type", choices=["odh", "rhoai"], default="rhoai")
    parser.add_argument("--require-dsc-ready", default="true")
    parser.add_argument("--require-kserve", default="true")
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--summary-md", required=True)
    args = parser.parse_args(argv)

    require_dsc_ready = args.require_dsc_ready.lower() == "true"
    require_kserve = args.require_kserve.lower() == "true"

    operator_profile = OPERATOR_PROFILES[args.cluster_type]

    try:
        # A NotFound deployment lookup is an expected signal (the operator may
        # only expose a CSV, not a well-known deployment name) so absence is
        # distinguished from a real oc error via run_oc_optional() rather
        # than swallowing every non-zero exit alike. When the deployment
        # exists, its readyReplicas vs spec.replicas is the sole health
        # signal (a stale-but-"Succeeded" CSV no longer masks an unhealthy
        # deployment); the CSV fallback only applies when the deployment
        # itself is genuinely absent. Every other probe below stays strict
        # (check=True) so genuine oc errors (auth, timeout, RBAC) still
        # hard-fail the gate instead of being silently swallowed.
        operator_ready_replicas, operator_deployment_exists = run_oc_optional(
            "get",
            "deployment",
            operator_profile["deployment"],
            "-n",
            operator_profile["namespace"],
            "-o",
            "jsonpath={.status.readyReplicas}",
        )
        operator_desired_replicas = ""
        csv_raw = ""
        if operator_deployment_exists:
            operator_desired_replicas = run_oc(
                "get",
                "deployment",
                operator_profile["deployment"],
                "-n",
                operator_profile["namespace"],
                "-o",
                "jsonpath={.spec.replicas}",
            )
        else:
            csv_raw = run_oc(
                "get",
                "csv",
                "-n",
                operator_profile["namespace"],
                "-o",
                "jsonpath={.items[*].status.phase}",
            )
        # `.items[0]` indexing errors out (non-zero exit, not a real oc
        # failure) when zero DataScienceCluster resources exist, which would
        # otherwise be indistinguishable from a genuine auth/timeout/RBAC
        # failure once caught below. List names first (safe on an empty list,
        # and still strict — a real oc error here still propagates) to tell
        # "genuinely absent" apart from "present but not ready".
        dsc_names_raw = run_oc(
            "get",
            "datasciencecluster",
            "-A",
            "-o",
            "jsonpath={.items[*].metadata.name}",
        )
        dsc_exists = bool(dsc_names_raw.strip())
        dsc_phase = ""
        false_conditions_raw = ""
        if dsc_exists:
            dsc_phase = run_oc(
                "get",
                "datasciencecluster",
                "-A",
                "-o",
                "jsonpath={.items[0].status.phase}",
            )
            false_conditions_raw = run_oc(
                "get",
                "datasciencecluster",
                "-A",
                "-o",
                'jsonpath={.items[0].status.conditions[?(@.status=="False")].type}',
            )
        # As with the DataScienceCluster probe above, list names first (safe
        # on an empty list) so a genuinely-absent KServe controller
        # deployment is distinguishable from a real oc error, instead of
        # indexing `.items[0]` on a possibly-empty list.
        kserve_names_raw = run_oc(
            "get",
            "deployment",
            "-A",
            "-l",
            KSERVE_LABEL_SELECTOR,
            "-o",
            "jsonpath={.items[*].metadata.name}",
        )
        kserve_exists = bool(kserve_names_raw.strip())
        kserve_ready_replicas = ""
        kserve_desired_replicas = ""
        if kserve_exists:
            kserve_ready_replicas = run_oc(
                "get",
                "deployment",
                "-A",
                "-l",
                KSERVE_LABEL_SELECTOR,
                "-o",
                "jsonpath={.items[0].status.readyReplicas}",
            )
            kserve_desired_replicas = run_oc(
                "get",
                "deployment",
                "-A",
                "-l",
                KSERVE_LABEL_SELECTOR,
                "-o",
                "jsonpath={.items[0].spec.replicas}",
            )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        summary = build_error_summary(args.cluster_profile, error)
        write_outputs(summary, Path(args.summary_json), Path(args.summary_md))
        return 1

    checks = [
        evaluate_operator_state(
            cluster_type=args.cluster_type,
            deployment_exists=operator_deployment_exists,
            ready_replicas=operator_ready_replicas,
            desired_replicas=operator_desired_replicas,
            csv_phases=csv_raw.split(),
        ),
        evaluate_dsc_state(
            phase=dsc_phase,
            false_conditions=false_conditions_raw.split(),
            require_ready=require_dsc_ready,
            exists=dsc_exists,
        ),
        evaluate_kserve_state(
            ready_replicas=kserve_ready_replicas,
            desired_replicas=kserve_desired_replicas,
            require_kserve=require_kserve,
            exists=kserve_exists,
        ),
    ]
    summary = build_summary(args.cluster_profile, checks)
    write_outputs(summary, Path(args.summary_json), Path(args.summary_md))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
