#!/bin/bash
set -euo pipefail

# =============================================================================
# OpenCode Data Directory Setup (session persistence)
# =============================================================================
# OpenCode stores config in ~/.config/opencode and session data in
# ~/.local/share/opencode. This function redirects both to a PVC-backed
# location so sessions persist across pod restarts.
# =============================================================================
setup_opencode_dirs() {
    export OPENCODE_DATA_DIR="${OPENCODE_DATA_DIR:-/opt/app-root/workspace/.opencode}"

    mkdir -p "${OPENCODE_DATA_DIR}/config/opencode"
    mkdir -p "${OPENCODE_DATA_DIR}/data/opencode"
    mkdir -p "${OPENCODE_DATA_DIR}/state/opencode"

    export XDG_CONFIG_HOME="${OPENCODE_DATA_DIR}/config"
    export XDG_DATA_HOME="${OPENCODE_DATA_DIR}/data"
    export XDG_STATE_HOME="${OPENCODE_DATA_DIR}/state"

    local home_config="${HOME}/.config"
    local home_data="${HOME}/.local/share"
    local home_state="${HOME}/.local/state"

    # Symlink ~/.config/opencode -> persistent config
    mkdir -p "${home_config}"
    if [[ -L "${home_config}/opencode" ]]; then
        local current_target
        current_target=$(readlink "${home_config}/opencode")
        if [[ "${current_target}" != "${XDG_CONFIG_HOME}/opencode" ]]; then
            ln -sfn "${XDG_CONFIG_HOME}/opencode" "${home_config}/opencode"
        fi
    else
        if [[ -d "${home_config}/opencode" ]]; then
            if [[ -n "$(ls -A "${home_config}/opencode" 2>/dev/null)" ]]; then
                cp -rn "${home_config}/opencode/"* "${XDG_CONFIG_HOME}/opencode/" 2>/dev/null || true
            fi
            mv "${home_config}/opencode" "${home_config}/opencode.migrated" 2>/dev/null || rm -rf "${home_config}/opencode" 2>/dev/null || true
        fi
        ln -sfn "${XDG_CONFIG_HOME}/opencode" "${home_config}/opencode" 2>/dev/null || true
    fi

    # Symlink ~/.local/share/opencode -> persistent data
    mkdir -p "${home_data}"
    if [[ -L "${home_data}/opencode" ]]; then
        local current_target
        current_target=$(readlink "${home_data}/opencode")
        if [[ "${current_target}" != "${XDG_DATA_HOME}/opencode" ]]; then
            ln -sfn "${XDG_DATA_HOME}/opencode" "${home_data}/opencode"
        fi
    else
        if [[ -d "${home_data}/opencode" ]]; then
            if [[ -n "$(ls -A "${home_data}/opencode" 2>/dev/null)" ]]; then
                cp -rn "${home_data}/opencode/"* "${XDG_DATA_HOME}/opencode/" 2>/dev/null || true
            fi
            mv "${home_data}/opencode" "${home_data}/opencode.migrated" 2>/dev/null || rm -rf "${home_data}/opencode" 2>/dev/null || true
        fi
        ln -sfn "${XDG_DATA_HOME}/opencode" "${home_data}/opencode" 2>/dev/null || true
    fi

    # Symlink ~/.local/state/opencode -> persistent state
    mkdir -p "${home_state}"
    if [[ -L "${home_state}/opencode" ]]; then
        local current_target
        current_target=$(readlink "${home_state}/opencode")
        if [[ "${current_target}" != "${XDG_STATE_HOME}/opencode" ]]; then
            ln -sfn "${XDG_STATE_HOME}/opencode" "${home_state}/opencode"
        fi
    else
        if [[ -d "${home_state}/opencode" ]]; then
            if [[ -n "$(ls -A "${home_state}/opencode" 2>/dev/null)" ]]; then
                cp -rn "${home_state}/opencode/"* "${XDG_STATE_HOME}/opencode/" 2>/dev/null || true
            fi
            mv "${home_state}/opencode" "${home_state}/opencode.migrated" 2>/dev/null || rm -rf "${home_state}/opencode" 2>/dev/null || true
        fi
        ln -sfn "${XDG_STATE_HOME}/opencode" "${home_state}/opencode" 2>/dev/null || true
    fi

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

# Build OpenCode config from template (jq handles special chars safely)
CONFIG=$(jq --arg base "$BASE_URL" --arg key "$API_KEY" --arg model "$MODEL_NAME" '
  .provider[].options.baseURL = $base |
  .provider[].options.apiKey = $key |
  .provider[].models = {($model): {name: $model}} |
  .model = $model |
  .small_model = $model
' /config-template/config-template.json)

# Merge MCP config if mounted
if [ -f /mcp-config/mcp-servers.json ]; then
  MCP_SERVERS=$(cat /mcp-config/mcp-servers.json)
  CONFIG=$(echo "$CONFIG" | jq --argjson mcp "$MCP_SERVERS" '. + {mcp: $mcp}')
fi

unset API_KEY BASE_URL MODEL_NAME

MODE="${OPENCODE_MODE:-web}"

case "$MODE" in
  web)
    export OPENCODE_CONFIG_CONTENT="$CONFIG"
    exec opencode web --hostname 0.0.0.0 --port 8003
    ;;
  cli)
    # Write config to persistent location for oc exec sessions
    echo "$CONFIG" > "${XDG_CONFIG_HOME}/opencode/opencode.json"
    echo "[entrypoint] CLI mode — config written to ${XDG_CONFIG_HOME}/opencode/opencode.json"
    echo "[entrypoint] Sessions persist in ${XDG_DATA_HOME}/opencode/"
    echo "[entrypoint] Attach with: oc exec -it deployment/opencode-cli -c opencode -- opencode"
    echo "[entrypoint] Resume last session: opencode --continue"
    exec sleep infinity
    ;;
  *)
    echo "[entrypoint] Unknown mode: $MODE (expected 'web' or 'cli')"
    exit 1
    ;;
esac
