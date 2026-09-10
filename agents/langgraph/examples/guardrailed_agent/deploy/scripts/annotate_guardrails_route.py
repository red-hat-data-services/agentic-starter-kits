#!/usr/bin/env python3
"""Poll for the guardrails OpenShift Route and apply the HAProxy timeout annotation.

QG4 integration tests reach the guardrails proxy via the external Route. The
default HAProxy server timeout (~30s) is too short for nemoguard chat latency;
this script sets ``haproxy.router.openshift.io/timeout`` after deploy.
"""

from __future__ import annotations

import argparse
import subprocess
import time

sleep = time.sleep

ROUTE_TIMEOUT_ANNOTATION = "haproxy.router.openshift.io/timeout"
DEFAULT_ROUTE_TIMEOUT = "120s"
DEFAULT_POLL_ATTEMPTS = 12
DEFAULT_POLL_INTERVAL_SECONDS = 5.0


def get_route_host(route_name: str, namespace: str, *, oc: str = "oc") -> str | None:
    """Return the Route host if it exists, otherwise None."""
    result = subprocess.run(
        [
            oc,
            "get",
            "route",
            route_name,
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.host}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    host = result.stdout.strip()
    return host or None


def annotate_route_timeout(
    route_name: str,
    namespace: str,
    timeout: str = DEFAULT_ROUTE_TIMEOUT,
    *,
    oc: str = "oc",
) -> None:
    """Apply the HAProxy timeout annotation to the guardrails Route."""
    result = subprocess.run(
        [
            oc,
            "annotate",
            "route",
            route_name,
            "-n",
            namespace,
            f"{ROUTE_TIMEOUT_ANNOTATION}={timeout}",
            "--overwrite",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise SystemExit(
            f"ERROR: Failed to annotate route {route_name} in {namespace}: {message}"
        )


def wait_for_route_and_annotate(
    route_name: str,
    namespace: str,
    *,
    timeout: str = DEFAULT_ROUTE_TIMEOUT,
    attempts: int = DEFAULT_POLL_ATTEMPTS,
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    oc: str = "oc",
    sleep=sleep,
) -> str:
    """Poll for the Route host, annotate it, and return the host."""
    host: str | None = None
    for attempt in range(1, attempts + 1):
        host = get_route_host(route_name, namespace, oc=oc)
        if host:
            break
        if attempt < attempts:
            sleep(interval_seconds)

    if not host:
        total_seconds = int(attempts * interval_seconds)
        raise SystemExit(
            f"ERROR: Guardrails Route '{route_name}' not found in namespace "
            f"'{namespace}' after {total_seconds}s. External QG4 tests require "
            "the operator-created Route and the HAProxy timeout annotation."
        )

    annotate_route_timeout(route_name, namespace, timeout, oc=oc)
    return host


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-name", required=True, help="OpenShift Route name")
    parser.add_argument("--namespace", required=True, help="Target namespace")
    parser.add_argument(
        "--timeout",
        default=DEFAULT_ROUTE_TIMEOUT,
        help=f"HAProxy timeout value (default: {DEFAULT_ROUTE_TIMEOUT})",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_POLL_ATTEMPTS,
        help=f"Route discovery poll attempts (default: {DEFAULT_POLL_ATTEMPTS})",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help=(
            "Seconds between Route discovery polls "
            f"(default: {DEFAULT_POLL_INTERVAL_SECONDS})"
        ),
    )
    args = parser.parse_args()

    host = wait_for_route_and_annotate(
        args.route_name,
        args.namespace,
        timeout=args.timeout,
        attempts=args.attempts,
        interval_seconds=args.interval_seconds,
    )
    print(f"Route URL: https://{host}")
    print(f"Applied {ROUTE_TIMEOUT_ANNOTATION}={args.timeout}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
