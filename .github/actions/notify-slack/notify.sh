#!/usr/bin/env bash
# Send a Slack payload via incoming webhook.
# Usage: ./notify.sh [--preview] PAYLOAD_PATH

set -euo pipefail

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to send Slack payloads" >&2
  exit 1
}

PREVIEW=false
if [[ "${1:-}" == "--preview" ]]; then
  PREVIEW=true
  shift
fi

PAYLOAD_PATH="${1:?Usage: $0 [--preview] PAYLOAD_PATH}"

if [[ ! -f "${PAYLOAD_PATH}" ]]; then
  echo "Payload file not found: ${PAYLOAD_PATH}" >&2
  exit 1
fi

jq empty "${PAYLOAD_PATH}" >/dev/null

if [[ "${PREVIEW}" == true ]]; then
  echo "::group::Slack payload preview (not sent)"
  jq . "${PAYLOAD_PATH}"
  echo "::endgroup::"
  exit 0
fi

WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

if [[ -z "${WEBHOOK_URL}" ]]; then
  echo "Slack webhook not configured, skipping notification"
  exit 0
fi

PAYLOAD="$(jq -c . "${PAYLOAD_PATH}")"

if [[ "${WEBHOOK_URL}" != https://* ]]; then
  echo "Invalid webhook URL (must start with https://)" >&2
  exit 1
fi

curl -fsS --connect-timeout 5 --max-time 10 \
  -X POST \
  -H 'Content-type: application/json' \
  --data "${PAYLOAD}" \
  "${WEBHOOK_URL}" >/dev/null

echo "Slack notification sent"
