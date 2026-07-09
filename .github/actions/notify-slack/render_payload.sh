#!/usr/bin/env bash
# Render a Slack Block Kit payload for CI failure notifications.

set -euo pipefail

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to render Slack payloads" >&2
  exit 1
}

WORKFLOW_NAME="${WORKFLOW_NAME:?WORKFLOW_NAME is required}"
EVENT_NAME="${EVENT_NAME:?EVENT_NAME is required}"
REF_NAME="${REF_NAME:?REF_NAME is required}"
RUN_URL="${RUN_URL:?RUN_URL is required}"
DASHBOARD_URL="${DASHBOARD_URL:?DASHBOARD_URL is required}"
REPOSITORY="${REPOSITORY:?REPOSITORY is required}"
STATUS="${STATUS:-failure}"
TIMESTAMP="${TIMESTAMP:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
FAILED_JOBS_JSON="${FAILED_JOBS_JSON:-[]}"

if ! jq -e 'type == "array"' <<<"${FAILED_JOBS_JSON}" >/dev/null 2>&1; then
  FAILED_JOBS_JSON='[]'
fi

case "${STATUS}" in
  failure | failed | timed_out)
    COLOR="#d00000"
    TITLE="CI Failure: ${WORKFLOW_NAME}"
    STATUS_LABEL="Failed"
    ;;
  cancelled | canceled)
    COLOR="#f2c744"
    TITLE="CI Cancelled: ${WORKFLOW_NAME}"
    STATUS_LABEL="Cancelled"
    ;;
  *)
    COLOR="#d00000"
    TITLE="CI Alert: ${WORKFLOW_NAME}"
    STATUS_LABEL="${STATUS}"
    ;;
esac

FAILED_JOBS_TEXT="$(
  jq -nr --argjson jobs "${FAILED_JOBS_JSON}" '
    if ($jobs | length) == 0 then
      "*Failed jobs*\n- Job details unavailable"
    elif ($jobs | length) <= 10 then
      "*Failed jobs*\n" + ($jobs | map("- `" + . + "`") | join("\n"))
    else
      "*Failed jobs*\n"
      + ($jobs[:10] | map("- `" + . + "`") | join("\n"))
      + "\n- ... and \((($jobs | length) - 10)) more"
    end
  '
)"

LINKS_TEXT="<${RUN_URL}|View workflow run> | <${DASHBOARD_URL}|View CI dashboard>"
FALLBACK_TEXT="CI ${STATUS_LABEL}: ${WORKFLOW_NAME} on ${REF_NAME}"

jq -n \
  --arg fallback_text "${FALLBACK_TEXT}" \
  --arg color "${COLOR}" \
  --arg title "${TITLE}" \
  --arg workflow_name "${WORKFLOW_NAME}" \
  --arg event_name "${EVENT_NAME}" \
  --arg ref_name "${REF_NAME}" \
  --arg repository "${REPOSITORY}" \
  --arg timestamp "${TIMESTAMP}" \
  --arg failed_jobs_text "${FAILED_JOBS_TEXT}" \
  --arg links_text "${LINKS_TEXT}" \
  '{
    text: $fallback_text,
    attachments: [
      {
        color: $color,
        blocks: [
          {
            type: "header",
            text: {
              type: "plain_text",
              text: $title,
              emoji: true
            }
          },
          {
            type: "section",
            fields: [
              {
                type: "mrkdwn",
                text: ("*Workflow*\n" + $workflow_name)
              },
              {
                type: "mrkdwn",
                text: ("*Event*\n" + $event_name)
              },
              {
                type: "mrkdwn",
                text: ("*Ref*\n" + $ref_name)
              },
              {
                type: "mrkdwn",
                text: ("*Time (UTC)*\n" + $timestamp)
              }
            ]
          },
          {
            type: "context",
            elements: [
              {
                type: "mrkdwn",
                text: ("Repository: `" + $repository + "`")
              }
            ]
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: $failed_jobs_text
            }
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: $links_text
            }
          }
        ]
      }
    ]
  }'
