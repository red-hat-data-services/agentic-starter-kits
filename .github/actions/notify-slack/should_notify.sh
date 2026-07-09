#!/usr/bin/env bash
# Decide whether a workflow run should emit a Slack notification.
# Outputs key=value pairs suitable for appending to GITHUB_OUTPUT.

set -euo pipefail

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to evaluate Slack notification gates" >&2
  exit 1
}

EVENT_NAME="${EVENT_NAME:?EVENT_NAME is required}"
REF_NAME="${REF_NAME:?REF_NAME is required}"
NEEDS_JSON="${NEEDS_JSON:-}"
if [[ -z "${NEEDS_JSON}" ]]; then
  NEEDS_JSON='{}'
fi

should_notify=false
status="success"
reason="all upstream jobs passed"

if [[ "${EVENT_NAME}" == "pull_request" ]]; then
  reason="pull request runs do not notify"
elif [[ "${EVENT_NAME}" == "workflow_dispatch" && "${REF_NAME}" != "main" ]]; then
  reason="manual dispatch outside main does not notify"
else
  status="$(
    jq -r '
      [.[] | .result] as $results
      | if any($results[]?; . == "failure") then "failure"
        elif any($results[]?; . == "timed_out") then "timed_out"
        elif any($results[]?; . == "cancelled") then "cancelled"
        else "success"
        end
    ' <<<"${NEEDS_JSON}"
  )"
  if [[ "${status}" != "success" ]]; then
    should_notify=true
    reason="workflow run failed"
  fi
fi

printf 'should_notify=%s\n' "${should_notify}"
printf 'status=%s\n' "${status}"
printf 'reason=%s\n' "${reason}"
