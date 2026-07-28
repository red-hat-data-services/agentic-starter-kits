#!/usr/bin/env bash
# codex-traced-exec.sh — runs codex exec then triggers the MLflow notify hook
# Usage: codex-traced-exec.sh --model qwen3.6-27b -c 'model_provider="vllm"' "your prompt here"
set -euo pipefail

# Ensure MLFLOW_TRACKING_TOKEN is set from SA token
if [[ -z "${MLFLOW_TRACKING_TOKEN:-}" ]]; then
    sa_token="/var/run/secrets/kubernetes.io/serviceaccount/token"
    if [[ -f "$sa_token" ]]; then
        export MLFLOW_TRACKING_TOKEN=$(cat "$sa_token")
    fi
fi
export NODE_TLS_REJECT_UNAUTHORIZED="${NODE_TLS_REJECT_UNAUTHORIZED:-0}"

# Run codex exec, passing all args through
codex exec "$@" 2>&1

# Find the most recent session file
session_dir="/workspace/.codex/sessions/$(date -u +%Y/%m/%d)"
latest=$(ls -t "$session_dir"/*.jsonl 2>/dev/null | head -1)

if [[ -z "$latest" ]]; then
    echo "[mlflow-trace] No session file found" >&2
    exit 0
fi

# Extract session ID from filename (format: rollout-<date>-<session-id>.jsonl)
session_id=$(basename "$latest" .jsonl | sed 's/rollout-[0-9T-]*-//')

# Build the notify payload from the session JSONL
export _LATEST_SESSION="$latest"
notify_payload=$(python3 << 'PYEOF'
import json, sys, os

session_file = os.environ.get("_LATEST_SESSION", "")
if not session_file:
    print("{}")
    sys.exit(0)

with open(session_file) as f:
    records = [json.loads(line) for line in f if line.strip()]

prompt = ""
assistant_msg = ""

for rec in records:
    if rec.get("type") == "response_item":
        payload = rec.get("payload", {})
        if payload.get("role") == "user":
            for c in payload.get("content", []):
                if isinstance(c, dict) and c.get("type") == "input_text":
                    prompt = c.get("text", "")

for rec in reversed(records):
    if rec.get("type") == "response_item":
        payload = rec.get("payload", {})
        if payload.get("role") == "assistant":
            for c in payload.get("content", []):
                if isinstance(c, dict) and "text" in c:
                    text = c["text"].strip()
                    if text:
                        assistant_msg = text
                        break
            if assistant_msg:
                break

session_meta = next(
    (r for r in records if r.get("type") == "session_meta"), {}
)
thread_id = session_meta.get("payload", {}).get("session_id", "")

result = {
    "type": "agent-turn-complete",
    "thread-id": thread_id,
    "input-messages": [prompt] if prompt else [],
    "last-assistant-message": assistant_msg or "(no response)"
}
print(json.dumps(result))
PYEOF
)

if [[ -z "$notify_payload" || "$notify_payload" == "{}" ]]; then
    echo "[mlflow-trace] Could not build notify payload" >&2
    exit 0
fi

echo "[mlflow-trace] Exporting trace for session $session_id..." >&2
mlflow-codex notify-hook "$notify_payload" 2>&1
echo "[mlflow-trace] Trace export complete" >&2
