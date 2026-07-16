#!/bin/bash
set -euo pipefail

# =============================================================================
# OpenCode Data Directory Setup (session persistence)
# =============================================================================
# OpenCode stores config in ~/.config/opencode and session data in
# ~/.local/share/opencode. This function redirects both to a PVC-backed
# location so sessions persist across pod restarts.
#
# XDG_STATE_HOME is exported here (not in the deployment manifest) so that
# all three XDG dirs are managed consistently. This also works around
# the container image creating ~/.local/state/ with 755 permissions,
# which prevents symlink creation under OpenShift's random UID.
# =============================================================================
redirect_xdg_dir() {
    local source_dir="$1"
    local target_dir="$2"

    mkdir -p "$(dirname "${source_dir}")"
    if [[ -L "${source_dir}" ]]; then
        local current_target
        current_target=$(readlink "${source_dir}")
        if [[ "${current_target}" != "${target_dir}" ]]; then
            ln -sfn "${target_dir}" "${source_dir}"
        fi
    else
        if [[ -d "${source_dir}" ]]; then
            if [[ -n "$(ls -A "${source_dir}" 2>/dev/null)" ]]; then
                cp -rn "${source_dir}/." "${target_dir}/" 2>/dev/null || true
            fi
            mv "${source_dir}" "${source_dir}.migrated" 2>/dev/null || { echo "[entrypoint] Warning: could not move ${source_dir}, removing"; rm -rf "${source_dir}" 2>/dev/null || true; }
        fi
        ln -sfn "${target_dir}" "${source_dir}" 2>/dev/null || true
    fi
}

setup_opencode_dirs() {
    export OPENCODE_DATA_DIR="${OPENCODE_DATA_DIR:-/opt/app-root/workspace/.opencode}"

    mkdir -p "${OPENCODE_DATA_DIR}/config/opencode"
    mkdir -p "${OPENCODE_DATA_DIR}/data/opencode"
    mkdir -p "${OPENCODE_DATA_DIR}/state/opencode"

    export XDG_CONFIG_HOME="${OPENCODE_DATA_DIR}/config"
    export XDG_DATA_HOME="${OPENCODE_DATA_DIR}/data"
    export XDG_STATE_HOME="${OPENCODE_DATA_DIR}/state"

    redirect_xdg_dir "${HOME}/.config/opencode"     "${XDG_CONFIG_HOME}/opencode"
    redirect_xdg_dir "${HOME}/.local/share/opencode" "${XDG_DATA_HOME}/opencode"
    redirect_xdg_dir "${HOME}/.local/state/opencode" "${XDG_STATE_HOME}/opencode"

    echo "[entrypoint] OpenCode data directory: ${OPENCODE_DATA_DIR}"
}

# =============================================================================
# Skills Configuration
# =============================================================================
# Skills are staged at /etc/opencode-skills/ (read-only ConfigMap mount)
# and symlinked into the config directory so OpenCode discovers them.
# =============================================================================
setup_skills() {
    local staged_skills="/etc/opencode-skills"
    local skills_dir="${XDG_CONFIG_HOME}/opencode/skills"

    if [[ -d "${staged_skills}" ]]; then
        mkdir -p "$(dirname "${skills_dir}")"

        if [[ -e "${skills_dir}" && ! -L "${skills_dir}" ]]; then
            local backup_dir="${skills_dir}.bak"
            local i=1
            while [[ -e "${backup_dir}" ]]; do
                backup_dir="${skills_dir}.bak.${i}"
                ((i++))
            done
            mv "${skills_dir}" "${backup_dir}"
            echo "[entrypoint] Moved existing skills directory to ${backup_dir}"
        fi

        ln -sfn "${staged_skills}" "${skills_dir}"

        local skill_count
        skill_count=$(find "${skills_dir}" -name "SKILL.md" -type f 2>/dev/null | wc -l)
        if [[ ${skill_count} -gt 0 ]]; then
            echo "[entrypoint] Found ${skill_count} skill(s) in ${skills_dir}"
        fi
    fi
}

# Git configuration
git config --global init.defaultBranch main
git config --global user.email "opencode@openshift.local"
git config --global user.name "OpenCode"
git config --global --add safe.directory /opt/app-root/workspace

# Setup persistent directories BEFORE config generation
setup_opencode_dirs
setup_skills

# Initialize workspace if needed
cd /opt/app-root/workspace
if [ ! -d .git ]; then
  git init
  git commit --allow-empty -m "init"
fi

# Exclude OpenCode internal data from git tracking
if ! grep -q "^\.opencode$" .gitignore 2>/dev/null; then
    echo ".opencode" >> .gitignore
fi

# Default SMALL_MODEL_NAME to MODEL_NAME if not set
export SMALL_MODEL_NAME="${SMALL_MODEL_NAME:-$MODEL_NAME}"

# Build OpenCode config from template (jq-based envsubst — replaces ${VAR}
# placeholders with matching environment variables, safely handling special chars)
CONFIG=$(jq '
  def envsubst:
    reduce ($ENV | to_entries[]) as $e (.;
      gsub("\\$\\{" + $e.key + "\\}"; $e.value)
    );
  walk(
    if type == "string" then envsubst
    elif type == "object" then with_entries(.key |= envsubst)
    else . end
  )
' /config-template/config-template.json)

# Register small model in provider model lists if different from primary
if [ -n "${SMALL_MODEL_NAME:-}" ] && [ "$SMALL_MODEL_NAME" != "$MODEL_NAME" ]; then
    CONFIG=$(echo "$CONFIG" | jq --arg sm "$SMALL_MODEL_NAME" '
      .provider[].models[$sm] = {name: $sm}
    ')
fi

# Merge MCP config if mounted
if [ -f /mcp-config/mcp-servers.json ]; then
  MCP_SERVERS=$(cat /mcp-config/mcp-servers.json)
  CONFIG=$(echo "$CONFIG" | jq --argjson mcp "$MCP_SERVERS" '. + {mcp: $mcp}')
fi

unset API_KEY BASE_URL MODEL_NAME SMALL_MODEL_NAME

MODE="${OPENCODE_MODE:-web}"

case "$MODE" in
  web)
    export OPENCODE_CONFIG_CONTENT="$CONFIG"
    exec opencode web --hostname 0.0.0.0 --port 8003
    ;;
  cli)
    # Write config to persistent location for oc exec sessions
    (umask 077 && echo "$CONFIG" > "${XDG_CONFIG_HOME}/opencode/opencode.json")
    echo "[entrypoint] CLI mode — config written to ${XDG_CONFIG_HOME}/opencode/opencode.json"
    echo "[entrypoint] Sessions persist in ${XDG_DATA_HOME}/opencode/"
    echo "[entrypoint] Attach with: oc exec -it deployment/opencode-web -c opencode-web -- opencode"
    echo "[entrypoint] Resume last session: opencode --continue"
    exec sleep infinity
    ;;
  *)
    echo "[entrypoint] Unknown mode: $MODE (expected 'web' or 'cli')"
    exit 1
    ;;
esac
