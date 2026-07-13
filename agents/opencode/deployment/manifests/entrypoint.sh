#!/bin/bash
set -euo pipefail

# Git configuration
git config --global init.defaultBranch main
git config --global user.email "opencode@openshift.local"
git config --global user.name "OpenCode"
git config --global --add safe.directory /opt/app-root/workspace

# Initialize workspace if needed
cd /opt/app-root/workspace
if [ ! -d .git ]; then
  git init
  git commit --allow-empty -m "init"
fi

# Build OpenCode config from template (envsubst handles special chars safely)
CONFIG=$(envsubst '${BASE_URL} ${API_KEY} ${MODEL_NAME}' < /config-template/config-template.json)

# Merge MCP config if mounted
if [ -f /mcp-config/mcp-servers.json ]; then
  MCP_SERVERS=$(cat /mcp-config/mcp-servers.json)
  CONFIG=$(echo "$CONFIG" | jq --argjson mcp "$MCP_SERVERS" '. + {mcp: $mcp}')
fi

export OPENCODE_CONFIG_CONTENT="$CONFIG"
unset API_KEY BASE_URL MODEL_NAME

MODE="${OPENCODE_MODE:-web}"

case "$MODE" in
  web)
    exec opencode web --hostname 0.0.0.0 --port 8003
    ;;
  cli)
    echo "[entrypoint] CLI mode — attach with: oc exec -it deployment/opencode-web -c opencode-web -- opencode"
    exec sleep infinity
    ;;
  *)
    echo "[entrypoint] Unknown mode: $MODE (expected 'web' or 'cli')"
    exit 1
    ;;
esac
