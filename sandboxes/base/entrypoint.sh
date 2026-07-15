#!/bin/bash
set -euo pipefail

AGENT="${1:-${AGENT_NAME:-bash}}"

install_agent() {
    local agent="$1"
    local script="/etc/openshell/agents/${agent}.sh"

    if [ -f "$script" ]; then
        echo "[openshell] Installing ${agent}..."
        bash "$script"
    else
        echo "[openshell] Unknown agent: ${agent}" >&2
        echo "[openshell] Available: $(ls /etc/openshell/agents/ 2>/dev/null | sed 's/\.sh$//' | tr '\n' ' ')" >&2
        exit 1
    fi
}

case "$AGENT" in
    bash)
        exec /bin/bash
        ;;
    *)
        if command -v "$AGENT" >/dev/null 2>&1; then
            shift 2>/dev/null || true
            exec "$AGENT" "$@"
        else
            install_agent "$AGENT"
            shift 2>/dev/null || true
            exec "$AGENT" "$@"
        fi
        ;;
esac
