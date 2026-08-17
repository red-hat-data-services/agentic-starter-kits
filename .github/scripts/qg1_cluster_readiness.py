from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

OC_TIMEOUT_SECONDS = 60


def parse_required_namespaces(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def run_oc(*args: str, timeout: float = OC_TIMEOUT_SECONDS) -> str:
    result = subprocess.run(
        ["oc", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def evaluate_cluster_state(
    *,
    api_health: str,
    cluster_version: str,
    gpu_nodes: list[str],
    namespaces: list[str],
    required_namespaces: list[str],
    require_gpu: bool,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    checks.append(
        {
            "name": "api_health",
            "passed": api_health == "ok",
            "details": "API healthy"
            if api_health == "ok"
            else f"API returned: {api_health or 'empty'}",
        }
    )
    checks.append(
        {
            "name": "cluster_version",
            "passed": bool(cluster_version),
            "details": f"Cluster version: {cluster_version}"
            if cluster_version
            else "Cluster version unavailable",
        }
    )
    if require_gpu:
        checks.append(
            {
                "name": "gpu_nodes",
                "passed": len(gpu_nodes) > 0,
                "details": f"Found {len(gpu_nodes)} GPU node(s)"
                if gpu_nodes
                else "No GPU nodes found",
            }
        )
    else:
        checks.append(
            {
                "name": "gpu_nodes",
                "passed": True,
                "details": "GPU requirement disabled",
            }
        )

    missing_namespaces = [ns for ns in required_namespaces if ns not in namespaces]
    checks.append(
        {
            "name": "required_namespaces",
            "passed": not missing_namespaces,
            "details": "All required namespaces present"
            if not missing_namespaces
            else f"Missing namespaces: {', '.join(missing_namespaces)}",
        }
    )
    return checks


def build_summary(
    cluster_profile: str, checks: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "cluster_profile": cluster_profile,
        "passed": all(bool(item["passed"]) for item in checks),
        "checks": checks,
    }


def build_error_summary(
    cluster_profile: str, error: subprocess.CalledProcessError
) -> dict[str, object]:
    command = " ".join(error.cmd) if isinstance(error.cmd, list) else str(error.cmd)
    stderr = (error.stderr or "").strip()
    details = f"Command failed ({command}): {stderr or 'no stderr output'}"
    return {
        "cluster_profile": cluster_profile,
        "passed": False,
        "checks": [
            {
                "name": "oc_command",
                "passed": False,
                "details": details,
            }
        ],
    }


def build_timeout_summary(
    cluster_profile: str, error: subprocess.TimeoutExpired
) -> dict[str, object]:
    command = " ".join(error.cmd) if isinstance(error.cmd, list) else str(error.cmd)
    details = f"Command timed out after {error.timeout}s ({command})"
    return {
        "cluster_profile": cluster_profile,
        "passed": False,
        "checks": [
            {
                "name": "oc_command",
                "passed": False,
                "details": details,
            }
        ],
    }


def write_outputs(summary: dict[str, object], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# QG1 Cluster Readiness",
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
    parser.add_argument("--require-gpu", default="true")
    parser.add_argument("--required-namespaces", default="ci-testing")
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--summary-md", required=True)
    args = parser.parse_args(argv)

    require_gpu = args.require_gpu.lower() == "true"
    required_namespaces = parse_required_namespaces(args.required_namespaces)

    try:
        api_health = run_oc("get", "--raw", "/healthz")
        cluster_version = run_oc(
            "get",
            "clusterversion",
            "-o",
            "jsonpath={.items[0].status.desired.version}",
        )
        gpu_raw = run_oc(
            "get",
            "nodes",
            "-l",
            "nvidia.com/gpu.present=true",
            "-o",
            "jsonpath={.items[*].metadata.name}",
        )
        ns_raw = run_oc("get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}")
    except subprocess.TimeoutExpired as error:
        summary = build_timeout_summary(args.cluster_profile, error)
        write_outputs(summary, Path(args.summary_json), Path(args.summary_md))
        return 1
    except subprocess.CalledProcessError as error:
        summary = build_error_summary(args.cluster_profile, error)
        write_outputs(summary, Path(args.summary_json), Path(args.summary_md))
        return 1

    checks = evaluate_cluster_state(
        api_health=api_health,
        cluster_version=cluster_version,
        gpu_nodes=[item for item in gpu_raw.split() if item],
        namespaces=[item for item in ns_raw.split() if item],
        required_namespaces=required_namespaces,
        require_gpu=require_gpu,
    )
    summary = build_summary(args.cluster_profile, checks)
    write_outputs(summary, Path(args.summary_json), Path(args.summary_md))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
