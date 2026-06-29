#!/bin/bash
# =============================================================================
# Claude Code Container Entrypoint
# =============================================================================
#
# This script handles environment setup before running Claude Code.
# It configures authentication, MCP servers, and other runtime settings
# based on environment variables passed to the container.
#
# Supported Environment Variables:
#
#   Authentication:
#     ANTHROPIC_API_KEY        - API key for Anthropic (or compatible endpoint)
#     ANTHROPIC_AUTH_TOKEN      - Bearer token (skips interactive key confirmation)
#     ANTHROPIC_BASE_URL       - Custom API endpoint (vLLM, OGX, etc.)
#
#   Vertex AI Authentication (alternative to ANTHROPIC_API_KEY):
#     CLAUDE_CODE_USE_VERTEX       - Set to "1" to enable Vertex AI mode
#     ANTHROPIC_VERTEX_PROJECT_ID  - GCP project ID with Vertex AI access
#     CLOUD_ML_REGION              - Vertex AI region (e.g., us-east5, global)
#     GOOGLE_APPLICATION_CREDENTIALS - Path to GCP service account key JSON
#
#   Model Configuration:
#     CLAUDE_MODEL             - Model to use (e.g., sonnet, opus, claude-sonnet-4-5-20250929)
#
#   MCP Configuration:
#     MCP_CONFIG_FILE          - Path to MCP configuration JSON file
#     MCP_CONFIG_JSON          - MCP configuration as inline JSON string
#
#   Git Credentials:
#     GITHUB_PAT               - GitHub Personal Access Token for push access
#     GIT_USER_NAME            - Git commit author name (default: claude-agent)
#     GIT_USER_EMAIL           - Git commit author email (default: claude-agent@noreply.github.com)
#
#   MLflow Tracing (optional):
#     MLFLOW_TRACKING_URI      - MLflow server URI (enables tracing when set)
#     MLFLOW_EXPERIMENT_NAME   - Experiment name (default: claude-code-traces)
#     MLFLOW_TRACKING_AUTH     - Auth plugin name (default: kubernetes-namespaced)
#     MLFLOW_WORKSPACE         - MLflow workspace (typically the namespace)
#     MLFLOW_TRACKING_INSECURE_TLS - Set to "true" to skip TLS cert verification
#
#   Permissions:
#     SKIP_PERMISSIONS         - Set to "true" to bypass permission checks (sandboxed environments only)
#
#   Session Persistence:
#     CLAUDE_CONFIG_DIR        - Directory for Claude Code state (default: /workspace/.claude)
#                                Session history and memory persist here across pod restarts.
#                                A symlink is created from ~/.claude to this directory.
#
# =============================================================================

set -euo pipefail

# Track temp files for cleanup
TEMP_FILES=()

cleanup_temp_files() {
    for f in "${TEMP_FILES[@]}"; do
        rm -f "$f" 2>/dev/null || true
    done
}
trap cleanup_temp_files EXIT

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log_info() {
    echo "[entrypoint] INFO: $*" >&2
}

log_warn() {
    echo "[entrypoint] WARN: $*" >&2
}

log_error() {
    echo "[entrypoint] ERROR: $*" >&2
}

# -----------------------------------------------------------------------------
# Onboarding
# -----------------------------------------------------------------------------

setup_onboarding() {
    local claude_json="${HOME}/.claude.json"
    log_info "Marking onboarding as complete (skips interactive login wizard)"
    if [[ -f "${claude_json}" ]]; then
        local merged
        merged=$(jq '.hasCompletedOnboarding = true' "${claude_json}" 2>/dev/null) \
            && echo "${merged}" > "${claude_json}" \
            && return
        # jq failed (malformed JSON or permissions), fall through to overwrite
        rm -f "${claude_json}" 2>/dev/null || true
    fi
    echo '{"hasCompletedOnboarding": true}' > "${claude_json}"
    chmod 660 "${claude_json}"
}

# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

validate_environment() {
    # Check authentication based on mode
    if [[ "${CLAUDE_CODE_USE_VERTEX:-}" == "1" ]]; then
        # Vertex AI mode - uses GCP credentials
        log_info "Vertex AI mode enabled"
        if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
            log_warn "GOOGLE_APPLICATION_CREDENTIALS not set. Vertex AI authentication may fail."
        elif [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
            log_warn "GOOGLE_APPLICATION_CREDENTIALS file not found: ${GOOGLE_APPLICATION_CREDENTIALS}"
        fi
        if [[ -z "${ANTHROPIC_VERTEX_PROJECT_ID:-}" ]]; then
            log_warn "ANTHROPIC_VERTEX_PROJECT_ID not set. Vertex AI requires a GCP project ID."
        fi
    else
        # API key or auth token mode
        if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
            log_warn "No authentication configured. Set ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or use Vertex AI mode (CLAUDE_CODE_USE_VERTEX=1)."
        fi
    fi

    # Log API endpoint if custom (don't log full URL - may contain credentials)
    if [[ -n "${ANTHROPIC_BASE_URL:-}" ]]; then
        log_info "Using custom API endpoint (value redacted)"
    fi

    # Log model if specified
    if [[ -n "${CLAUDE_MODEL:-}" ]]; then
        log_info "Using model: ${CLAUDE_MODEL}"
    fi
}

# -----------------------------------------------------------------------------
# Git Credentials
# -----------------------------------------------------------------------------

setup_git_credentials() {
    if [[ -n "${GITHUB_PAT:-}" ]]; then
        log_info "Configuring git credentials for github.com"
        git config --global credential.helper store
        local cred_file="${HOME}/.git-credentials"
        echo "https://x-access-token:${GITHUB_PAT}@github.com" > "${cred_file}"
        chmod 600 "${cred_file}"
        git config --global user.name "${GIT_USER_NAME:-claude-agent}"
        git config --global user.email "${GIT_USER_EMAIL:-claude-agent@noreply.github.com}"
    fi
}

# -----------------------------------------------------------------------------
# Config Directory Setup (Session Persistence)
# -----------------------------------------------------------------------------

setup_config_dir() {
    # Use CLAUDE_CONFIG_DIR for Claude Code state, defaulting to /workspace/.claude
    # This enables session persistence since /workspace is backed by a PVC
    export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/workspace/.claude}"

    # Ensure the config directory exists and is group-writable.
    # On OpenShift, fresh PVCs are owned by root with the pod's fsGroup.
    # The non-root container user writes via group membership, so directories
    # must be group-writable (g+w).
    mkdir -p "${CLAUDE_CONFIG_DIR}"
    chmod g+w "${CLAUDE_CONFIG_DIR}" 2>/dev/null || true

    # Ensure the projects directory exists (WORKDIR is /workspace/projects)
    # This separates global config (/workspace/.claude) from local auto-memory (/workspace/projects/.claude)
    mkdir -p /workspace/projects
    chmod g+w /workspace/projects 2>/dev/null || true

    # Create symlink from ~/.claude to the config dir for user convenience
    # Users expect to find settings/skills at ~/.claude/
    # The image doesn't include ~/.claude (removed at build time), so we just create the symlink
    local home_claude_dir="${HOME}/.claude"
    if [[ -L "${home_claude_dir}" ]]; then
        # Symlink exists - verify it points to the correct location
        local current_target
        current_target=$(readlink "${home_claude_dir}")
        if [[ "${current_target}" != "${CLAUDE_CONFIG_DIR}" ]]; then
            ln -sfn "${CLAUDE_CONFIG_DIR}" "${home_claude_dir}"
            log_info "Updated symlink: ${home_claude_dir} -> ${CLAUDE_CONFIG_DIR}"
        fi
    else
        # No symlink - remove any existing directory and create the symlink
        if [[ -d "${home_claude_dir}" ]]; then
            log_info "Removing existing ${home_claude_dir} directory"
            rm -rf "${home_claude_dir}" 2>/dev/null || mv -f "${home_claude_dir}" "${home_claude_dir}.old" 2>/dev/null || true
        fi
        ln -sfn "${CLAUDE_CONFIG_DIR}" "${home_claude_dir}"
    fi

    # Copy staged settings.json from ConfigMap mount to writable PVC location.
    # ConfigMap subPath mounts are read-only, but mlflow autolog needs to write
    # hook configuration into settings.json. Staging at /etc/claude-config/ and
    # copying here makes the file writable. Only copy if the target doesn't
    # already exist, so runtime changes (e.g., mlflow autolog hooks) survive
    # pod restarts.
    local staged_settings="/etc/claude-config/settings.json"
    local target_settings="${CLAUDE_CONFIG_DIR}/settings.json"
    if [[ -f "${staged_settings}" && ! -s "${target_settings}" ]]; then
        cp "${staged_settings}" "${target_settings}"
        log_info "Copied settings from ${staged_settings} to ${target_settings}"
    elif [[ -s "${target_settings}" ]]; then
        log_info "Preserving existing ${target_settings}"
    fi

    log_info "Claude config directory: ${CLAUDE_CONFIG_DIR}"
    log_info "Symlink: ${home_claude_dir} -> ${CLAUDE_CONFIG_DIR}"
}

# -----------------------------------------------------------------------------
# MCP Configuration
# -----------------------------------------------------------------------------

setup_mcp() {
    local mcp_args=()

    # MCP config from file
    if [[ -n "${MCP_CONFIG_FILE:-}" ]]; then
        if [[ -f "${MCP_CONFIG_FILE}" ]]; then
            log_info "Loading MCP config from file: ${MCP_CONFIG_FILE}"
            mcp_args+=("--mcp-config" "${MCP_CONFIG_FILE}")
        else
            log_error "MCP_CONFIG_FILE specified but not found: ${MCP_CONFIG_FILE}"
            exit 1
        fi
    fi

    # MCP config from inline JSON - write to temp file since --mcp-config expects a path
    if [[ -n "${MCP_CONFIG_JSON:-}" ]]; then
        local tmp_mcp_config
        tmp_mcp_config=$(mktemp /tmp/mcp-config-XXXXXX.json)
        TEMP_FILES+=("${tmp_mcp_config}")
        echo "${MCP_CONFIG_JSON}" > "${tmp_mcp_config}"
        log_info "Loading MCP config from environment variable (written to ${tmp_mcp_config})"
        mcp_args+=("--mcp-config" "${tmp_mcp_config}")
    fi

    # Export for use in command building
    export MCP_ARGS="${mcp_args[*]:-}"
}

# -----------------------------------------------------------------------------
# MLflow Tracing
# -----------------------------------------------------------------------------

setup_mlflow() {
    if [[ -z "${MLFLOW_TRACKING_URI:-}" ]]; then
        return
    fi

    if ! command -v mlflow >/dev/null 2>&1; then
        log_warn "MLFLOW_TRACKING_URI is set but mlflow is not installed"
        return
    fi

    log_info "Configuring MLflow tracing"

    export MLFLOW_TRACKING_AUTH="${MLFLOW_TRACKING_AUTH:-kubernetes-namespaced}"
    export MLFLOW_TRACKING_INSECURE_TLS="${MLFLOW_TRACKING_INSECURE_TLS:-false}"

    if [[ "${MLFLOW_TRACKING_INSECURE_TLS}" == "true" ]]; then
        log_warn "MLflow TLS certificate verification is disabled (MLFLOW_TRACKING_INSECURE_TLS=true)"
    fi

    if ! mlflow autolog claude \
        -d /workspace \
        -u "${MLFLOW_TRACKING_URI}" \
        -n "${MLFLOW_EXPERIMENT_NAME:-claude-code-traces}"; then
        log_warn "mlflow autolog failed. Tracing will not be available, but Claude Code will still work."
        return
    fi

    # Inject MLflow auth env vars into the generated settings
    if ! python3 -c '
import json, os, sys
config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "/workspace/.claude")
sf = os.path.join(config_dir, "settings.json")
if not os.path.exists(sf):
    print(f"[entrypoint] WARN: {sf} not found, skipping MLflow settings injection")
    sys.exit(0)
try:
    with open(sf) as f:
        s = json.load(f)
except json.JSONDecodeError:
    print(f"[entrypoint] WARN: {sf} contains invalid JSON, skipping MLflow settings injection")
    sys.exit(0)
env = s.setdefault("env", {})
env["MLFLOW_TRACKING_AUTH"] = os.environ.get("MLFLOW_TRACKING_AUTH", "kubernetes-namespaced")
env["MLFLOW_WORKSPACE"] = os.environ.get("MLFLOW_WORKSPACE", "")
env["MLFLOW_TRACKING_INSECURE_TLS"] = os.environ.get("MLFLOW_TRACKING_INSECURE_TLS", "false")
# Inject SA token for npm plugin (Python SDK reads it automatically, Node.js does not)
sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
try:
    with open(sa_token_path) as f:
        env["MLFLOW_TRACKING_TOKEN"] = f.read().strip()
except FileNotFoundError:
    pass
with open(sf, "w") as f:
    json.dump(s, f, indent=2)
print("[entrypoint] INFO: MLflow settings injected into " + sf)
'; then
        log_warn "MLflow settings injection failed. Tracing may not authenticate correctly."
    fi

    # Replace installed plugin bundle with pre-built version if available
    # (needed until the npm plugin release includes the workspace header fix)
    if [[ -f "/opt/mlflow-plugin/stop.cjs" ]]; then
        local cached_stop
        cached_stop=$(find "${CLAUDE_CONFIG_DIR:-/workspace/.claude}/plugins" -name "stop.cjs" -path "*/mlflow*" 2>/dev/null | head -1)
        if [[ -n "${cached_stop}" ]]; then
            cp /opt/mlflow-plugin/stop.cjs "${cached_stop}"
            log_info "Replaced plugin bundle with pre-built version"
        fi
    fi
}

# -----------------------------------------------------------------------------
# Skills Configuration
# -----------------------------------------------------------------------------

setup_skills() {
    # Skills are staged at /etc/claude-skills/ (read-only ConfigMap mount) and
    # symlinked into $CLAUDE_CONFIG_DIR/skills/ so Claude Code discovers them.
    # We mount outside the PVC to avoid Kubernetes creating /workspace/.claude/
    # as root with restrictive permissions on fresh PVCs.
    local staged_skills="/etc/claude-skills"
    local skills_dir="${CLAUDE_CONFIG_DIR}/skills"

    if [[ -d "${staged_skills}" ]]; then
        if [[ -e "${skills_dir}" && ! -L "${skills_dir}" ]]; then
            local backup_dir="${skills_dir}.bak"
            local i=1
            while [[ -e "${backup_dir}" ]]; do
                backup_dir="${skills_dir}.bak.${i}"
                ((i++))
            done
            mv "${skills_dir}" "${backup_dir}"
            log_info "Moved existing skills directory to ${backup_dir}"
        fi
        ln -sfn "${staged_skills}" "${skills_dir}"
        local skill_count
        skill_count=$(find "${skills_dir}" -name "SKILL.md" -type f 2>/dev/null | wc -l)
        if [[ ${skill_count} -gt 0 ]]; then
            log_info "Found ${skill_count} skill(s) in ${skills_dir}"
        else
            log_info "No skills found (mount skills to ${staged_skills})"
        fi
    fi
}

# -----------------------------------------------------------------------------
# Build Command Arguments
# -----------------------------------------------------------------------------

build_claude_args() {
    local args=()

    # Model selection
    if [[ -n "${CLAUDE_MODEL:-}" ]]; then
        args+=("--model" "${CLAUDE_MODEL}")
    fi

    # MCP configuration
    if [[ -n "${MCP_ARGS:-}" ]]; then
        # shellcheck disable=SC2206
        args+=(${MCP_ARGS})
    fi

    # Permission bypass for sandboxed environments
    if [[ "${SKIP_PERMISSIONS:-false}" == "true" ]]; then
        log_warn "Permission checks disabled (SKIP_PERMISSIONS=true)"
        args+=("--dangerously-skip-permissions")
    fi

    # Add workspace directory access
    args+=("--add-dir" "/workspace")

    # Export for use in exec
    # NOTE: Flattening array to string loses proper quoting. This is acceptable
    # because our flags (--model, --mcp-config, --add-dir, --dangerously-skip-permissions)
    # don't contain spaces.
    # shellcheck disable=SC2124
    export CLAUDE_EXTRA_ARGS="${args[*]:-}"

    # Persist args to file so oc exec sessions can use them
    # Users can: source ~/.claude/env.sh && claude $CLAUDE_EXTRA_ARGS -p "..."
    # Or use the claude-run wrapper: claude-run -p "..."
    local claude_dir="${HOME}/.claude"
    mkdir -p "${claude_dir}"

    # Write environment file
    cat > "${claude_dir}/env.sh" <<EOF
# Generated by entrypoint.sh at container start
# Source this file in oc exec sessions to get the same args as the entrypoint
export CLAUDE_EXTRA_ARGS="${args[*]:-}"
EOF

    # Create wrapper script in user's home (since /usr/local/bin is read-only at runtime)
    cat > "${claude_dir}/claude-run" <<'WRAPPER'
#!/bin/bash
# Wrapper script that runs claude with the container's configured args
# Usage: claude-run [additional-args...]
source "${HOME}/.claude/env.sh" 2>/dev/null || true
# shellcheck disable=SC2086
exec claude ${CLAUDE_EXTRA_ARGS} "$@"
WRAPPER
    chmod +x "${claude_dir}/claude-run"

    # Add to PATH via .bashrc if not already there
    if ! grep -q 'claude-run' "${HOME}/.bashrc" 2>/dev/null; then
        echo 'export PATH="${HOME}/.claude:${PATH}"' >> "${HOME}/.bashrc"
    fi

    log_info "Claude args persisted to ${claude_dir}/env.sh"
    log_info "Wrapper script available: claude-run (or ~/.claude/claude-run)"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    log_info "Starting Claude Code container"
    log_info "Claude Code version: $(claude --version 2>/dev/null || echo 'unknown')"

    # Run setup functions
    setup_onboarding
    validate_environment
    setup_git_credentials
    setup_config_dir
    setup_mcp
    setup_mlflow
    setup_skills
    build_claude_args

    # If no arguments provided, show help
    if [[ $# -eq 0 ]]; then
        log_info "No command provided. Running: claude --help"
        exec claude --help
    fi

    # If first argument is "claude", run it with our extra args
    if [[ "$1" == "claude" ]]; then
        shift
        log_info "Running: claude ${CLAUDE_EXTRA_ARGS}"
        # shellcheck disable=SC2086
        exec claude ${CLAUDE_EXTRA_ARGS} "$@"
    fi

    # Otherwise, run the command as-is (allows running bash, sh, etc.)
    log_info "Running custom command: $1"
    exec "$@"
}

main "$@"
