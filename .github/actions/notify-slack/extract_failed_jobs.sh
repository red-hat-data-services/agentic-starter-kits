#!/usr/bin/env bash
# Extract failed or cancelled job names from a GitHub Actions jobs API payload.

set -euo pipefail

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to parse failed job payloads" >&2
  exit 1
}

INPUT_PATH="${1:-}"

if [[ -n "${INPUT_PATH}" ]]; then
  jq -c '[.jobs[]? | select(.conclusion == "failure" or .conclusion == "cancelled" or .conclusion == "timed_out") | .name]' "${INPUT_PATH}"
else
  jq -c '[.jobs[]? | select(.conclusion == "failure" or .conclusion == "cancelled" or .conclusion == "timed_out") | .name]'
fi
