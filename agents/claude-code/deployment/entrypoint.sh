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
#   Permissions:
#     SKIP_PERMISSIONS         - Set to "true" to bypass permission checks (sandboxed environments only)
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
        # Standard Anthropic API mode
        if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
            log_warn "ANTHROPIC_API_KEY not set. Claude Code may not be able to authenticate."
            log_warn "Set ANTHROPIC_API_KEY or use Vertex AI mode (CLAUDE_CODE_USE_VERTEX=1)."
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
# Skills Configuration
# -----------------------------------------------------------------------------

setup_skills() {
    # Claude Code auto-discovers skills from ~/.claude/skills/
    # Structure: ~/.claude/skills/<skill-name>/SKILL.md
    local skills_dir="${HOME}/.claude/skills"

    if [[ -d "${skills_dir}" ]]; then
        local skill_count
        skill_count=$(find "${skills_dir}" -name "SKILL.md" -type f 2>/dev/null | wc -l)
        if [[ ${skill_count} -gt 0 ]]; then
            log_info "Found ${skill_count} skill(s) in ${skills_dir}"
        else
            log_info "No skills found (mount skills to ${skills_dir})"
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
    validate_environment
    setup_mcp
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
