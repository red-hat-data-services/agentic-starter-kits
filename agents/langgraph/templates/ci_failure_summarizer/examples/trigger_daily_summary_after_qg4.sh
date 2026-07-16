#!/usr/bin/env bash
# Example: trigger a daily CI triage summary after the QG4 workflow finishes.
#
# Prerequisites:
#   - Agent deployed and reachable (local dev or OpenShift route)
#   - GITHUB_REPOSITORY / GITHUB_WORKFLOW configured on the agent
#   - SLACK_WEBHOOK_URL set when you want Slack delivery
#
# Usage:
#   ./examples/trigger_daily_summary_after_qg4.sh
#   AGENT_URL=https://langgraph-ci-failure-summarizer-agent-ci-testing.apps.example.com \
#     ./examples/trigger_daily_summary_after_qg4.sh
#
# Set POST_TO_SLACK=false to dry-run the summary without posting.

set -euo pipefail

AGENT_URL="${AGENT_URL:-http://localhost:8000}"
POST_TO_SLACK="${POST_TO_SLACK:-true}"
RUN_ID="${RUN_ID:-}"

payload='{"post_to_slack": '"$POST_TO_SLACK"'}'
if [[ -n "$RUN_ID" ]]; then
  payload='{"run_id": '"$RUN_ID"', "post_to_slack": '"$POST_TO_SLACK"'}'
fi

echo "Triggering CI failure summary at ${AGENT_URL}/summarize"
response="$(curl -sS -X POST "${AGENT_URL}/summarize" \
  -H 'Content-Type: application/json' \
  -d "${payload}")"

echo "$response" | python3 -m json.tool
echo ""
echo "Summary text:"
echo "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["summary_text"])'
