#!/usr/bin/env python3
"""Poll for the guardrails Route and set HAProxy timeout for QG4 external tests."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

POLL_ATTEMPTS = 12
POLL_INTERVAL_SECONDS = 5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-name", required=True)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()

    host = ""
    for attempt in range(1, POLL_ATTEMPTS + 1):
        result = subprocess.run(
            [
                "oc",
                "get",
                "route",
                args.route_name,
                "-n",
                args.namespace,
                "-o",
                "jsonpath={.spec.host}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        host = result.stdout.strip()
        if host:
            break
        if attempt < POLL_ATTEMPTS:
            time.sleep(POLL_INTERVAL_SECONDS)

    if not host:
        print(
            f"ERROR: Guardrails Route '{args.route_name}' not found in "
            f"'{args.namespace}' after {POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s.",
            file=sys.stderr,
        )
        return 1

    annotate = subprocess.run(
        [
            "oc",
            "annotate",
            "route",
            args.route_name,
            "-n",
            args.namespace,
            "haproxy.router.openshift.io/timeout=120s",
            "--overwrite",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if annotate.returncode != 0:
        message = annotate.stderr.strip() or annotate.stdout.strip() or "unknown error"
        print(f"ERROR: Failed to annotate route: {message}", file=sys.stderr)
        return 1

    print(f"Route URL: https://{host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
