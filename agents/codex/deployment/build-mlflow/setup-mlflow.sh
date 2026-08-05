#!/usr/bin/env bash
set -euo pipefail

log_info()  { echo "[mlflow-setup] $*" >&2; }
log_warn()  { echo "[mlflow-setup] WARNING: $*" >&2; }

setup_mlflow() {
    if [[ -z "${MLFLOW_TRACKING_URI:-}" ]]; then
        log_info "MLFLOW_TRACKING_URI not set — skipping MLflow tracing setup"
        return
    fi

    log_info "Configuring MLflow tracing → ${MLFLOW_TRACKING_URI}"

    export CODEX_HOME="${CODEX_HOME:-/workspace/.codex}"
    mkdir -p "${CODEX_HOME}"
    export MLFLOW_TRACKING_AUTH="${MLFLOW_TRACKING_AUTH:-kubernetes-namespaced}"

    local experiment_name="${MLFLOW_EXPERIMENT_NAME:-codex-traces}"

    # 1. SA token for MLflow auth
    local sa_token_path="/var/run/secrets/kubernetes.io/serviceaccount/token"
    if [[ -f "${sa_token_path}" ]]; then
        export MLFLOW_TRACKING_TOKEN
        MLFLOW_TRACKING_TOKEN=$(cat "${sa_token_path}")
        log_info "SA token loaded from ${sa_token_path}"
    else
        log_warn "SA token not found at ${sa_token_path}"
    fi

    # 2. Auto-create experiment
    python3 -c "
import mlflow, os
mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])
name = os.environ.get('MLFLOW_EXPERIMENT_NAME', 'codex-traces')
try:
    mlflow.set_experiment(name)
    print(f'[mlflow-setup] Experiment ready: {name}')
except Exception as e:
    print(f'[mlflow-setup] WARNING: Could not create experiment: {e}')
" 2>&1 || log_warn "Experiment creation failed (non-fatal)"

    # 3. Register notify hook via mlflow-codex and fix config locations
    if command -v mlflow-codex >/dev/null 2>&1; then
        export MLFLOW_TRACKING_URI
        export MLFLOW_EXPERIMENT_NAME="${experiment_name}"

        # Get experiment ID for mlflow-tracing.json
        local exp_id="${MLFLOW_EXPERIMENT_ID:-}"
        if [[ -z "${exp_id}" ]]; then
            exp_id=$(python3 -c "
import mlflow, os, sys
mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])
name = os.environ.get('MLFLOW_EXPERIMENT_NAME', 'codex-traces')
exp = mlflow.get_experiment_by_name(name)
if not exp:
    print(f'[mlflow-setup] ERROR: experiment {name!r} not found', file=sys.stderr)
    sys.exit(1)
print(exp.experiment_id)
" 2>/dev/null) || { log_warn "Could not resolve experiment ID for '${experiment_name}' — skipping hook setup"; return; }
        fi

        export MLFLOW_EXPERIMENT_ID="${exp_id}"

        # Write mlflow-tracing.json to CODEX_HOME
        cat > "${CODEX_HOME}/mlflow-tracing.json" <<TRACING_JSON
{
  "trackingUri": "${MLFLOW_TRACKING_URI}",
  "experimentId": "${exp_id}"
}
TRACING_JSON

        # Also write to $HOME/.codex/ — @mlflow/codex resolves user-level
        # config from ~ (HOME), not CODEX_HOME. Skip if they resolve to
        # the same directory (entrypoint.sh symlinks ~/.codex -> CODEX_HOME).
        if [[ "$(realpath "${HOME}/.codex" 2>/dev/null)" != "$(realpath "${CODEX_HOME}" 2>/dev/null)" ]]; then
            mkdir -p "${HOME}/.codex"
            cp "${CODEX_HOME}/mlflow-tracing.json" "${HOME}/.codex/mlflow-tracing.json"
        fi
        log_info "mlflow-tracing.json written (experiment ${exp_id})"

        # Ensure notify hook is in user-level config.toml.
        # IMPORTANT: notify must be a TOP-LEVEL key — placing it after any
        # [section] header causes TOML to nest it under that section, where
        # Codex will never read it.
        if grep -q 'mlflow-codex-hook\.sh' "${CODEX_HOME}/config.toml" 2>/dev/null; then
            log_info "Notify hook already in config.toml"
        elif grep -q '^notify = ' "${CODEX_HOME}/config.toml" 2>/dev/null; then
            sed -i 's|^notify = .*|notify = ["mlflow-codex-hook.sh"]|' "${CODEX_HOME}/config.toml"
            log_info "Notify hook replaced in existing config"
        else
            # Insert before the first [section] header so it stays top-level
            local first_section
            first_section=$(grep -n '^\[' "${CODEX_HOME}/config.toml" 2>/dev/null | head -1 | cut -d: -f1)
            if [[ -n "${first_section}" ]]; then
                sed -i "${first_section}i\\
\\
# MLflow tracing — forwards each Codex turn to MLflow\\
notify = [\"mlflow-codex-hook.sh\"]" "${CODEX_HOME}/config.toml"
            else
                {
                    echo ''
                    echo '# MLflow tracing — forwards each Codex turn to MLflow'
                    echo 'notify = ["mlflow-codex-hook.sh"]'
                } >> "${CODEX_HOME}/config.toml"
            fi
            log_info "Notify hook added to user-level config.toml"
        fi

        # Fix project-level mlflow-tracing.json if it exists with wrong values
        local proj_tracing="/workspace/projects/.codex/mlflow-tracing.json"
        if [[ -d "/workspace/projects/.codex" ]]; then
            cat > "${proj_tracing}" <<TRACING_JSON
{
  "trackingUri": "${MLFLOW_TRACKING_URI}",
  "experimentId": "${exp_id}"
}
TRACING_JSON
            log_info "Project-level mlflow-tracing.json updated"
        fi

        # 4. Write .mlflow-env for the notify hook and interactive oc exec sessions
        cat > "${CODEX_HOME}/.mlflow-env" <<MLFLOW_ENV
_sa_token="/var/run/secrets/kubernetes.io/serviceaccount/token"
if [[ -f "\${_sa_token}" ]]; then
    export MLFLOW_TRACKING_TOKEN=\$(cat "\${_sa_token}")
fi
unset _sa_token
export MLFLOW_EXPERIMENT_ID="${exp_id}"
MLFLOW_ENV

        # 5. Source from .bashrc for oc exec sessions
        if ! grep -q 'mlflow-env' "${HOME}/.bashrc" 2>/dev/null; then
            echo 'source "${CODEX_HOME}/.mlflow-env" 2>/dev/null || true' >> "${HOME}/.bashrc"
        fi
    else
        log_warn "mlflow-codex not found on PATH"
    fi

    log_info "MLflow tracing setup complete"
}

setup_mlflow

if [[ $# -gt 0 ]]; then
    exec "$@"
else
    exec sleep infinity
fi
