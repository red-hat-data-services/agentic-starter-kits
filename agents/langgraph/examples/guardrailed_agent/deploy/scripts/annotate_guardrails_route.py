#!/usr/bin/env python3
"""Poll for the guardrails Route and set HAProxy timeout for QG4 external tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

OC_BIN = os.environ.get("OC_BIN", "oc")
OC_TIMEOUT_SECONDS = int(os.environ.get("OC_TIMEOUT_SECONDS", "30"))
POLL_ATTEMPTS = int(os.environ.get("POLL_ATTEMPTS", "12"))
POLL_INTERVAL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "5"))


def _run_oc(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [OC_BIN, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=OC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: oc timed out after {OC_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-name", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument(
        "--required",
        action="store_true",
        help="Fail deploy when the external Route is not found (CI / QG4).",
    )
    args = parser.parse_args()

    host = ""
    for attempt in range(1, POLL_ATTEMPTS + 1):
        result = _run_oc(
            [
                "get",
                "route",
                args.route_name,
                "-n",
                args.namespace,
                "-o",
                "jsonpath={.spec.host}",
            ]
        )
        if result is None:
            return 1
        host = result.stdout.strip()
        if host:
            break
        if attempt < POLL_ATTEMPTS:
            time.sleep(POLL_INTERVAL_SECONDS)

    if not host:
        message = (
            f"Guardrails Route '{args.route_name}' not found in "
            f"'{args.namespace}' after {POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s."
        )
        if args.required:
            print(f"ERROR: {message}", file=sys.stderr)
            return 1
        print(f"WARNING: {message}", file=sys.stderr)
        return 0

    annotate = _run_oc(
        [
            "annotate",
            "route",
            args.route_name,
            "-n",
            args.namespace,
            "haproxy.router.openshift.io/timeout=120s",
            "--overwrite",
        ]
    )
    if annotate is None:
        return 1
    if annotate.returncode != 0:
        message = annotate.stderr.strip() or annotate.stdout.strip() or "unknown error"
        print(f"ERROR: Failed to annotate route: {message}", file=sys.stderr)
        return 1

    print(f"Route URL: https://{host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
