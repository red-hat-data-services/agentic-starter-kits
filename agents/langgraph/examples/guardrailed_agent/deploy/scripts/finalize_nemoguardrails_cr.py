#!/usr/bin/env python3
"""Drop unused OTEL env from a substituted NemoGuardrails CR when tracing is off.

Reads a YAML CR from PATH (after envsubst) and strips OTEL_* env vars unless
GUARDRAILS_TRACING_ENABLED is exactly ``true``. When tracing is on, requires a
non-empty OTEL_EXPORTER_OTLP_ENDPOINT. Writes the result back to PATH.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

_OTEL_ENV_NAMES = {
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_METRICS_EXPORTER",
}
_DROP_ALWAYS = {"GUARDRAILS_TRACING_ENABLED"}


def _tracing_enabled() -> bool:
    return os.environ.get("GUARDRAILS_TRACING_ENABLED", "") == "true"


def finalize(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    env = list(doc.get("spec", {}).get("env") or [])
    env = [entry for entry in env if entry.get("name") not in _DROP_ALWAYS]
    enabled = _tracing_enabled()
    if enabled:
        endpoint = next(
            (
                str(entry.get("value") or "")
                for entry in env
                if entry.get("name") == "OTEL_EXPORTER_OTLP_ENDPOINT"
            ),
            "",
        )
        if not endpoint.strip() or "${" in endpoint:
            raise SystemExit(
                "ERROR: GUARDRAILS_TRACING_ENABLED is on but "
                "OTEL_EXPORTER_OTLP_ENDPOINT is empty or unsubstituted. "
                "Set it in cluster.env to the Tempo OTLP gRPC service."
            )
    else:
        env = [entry for entry in env if entry.get("name") not in _OTEL_ENV_NAMES]
    doc.setdefault("spec", {})["env"] = env
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Substituted NemoGuardrails CR YAML")
    args = parser.parse_args()
    try:
        finalize(args.path)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
