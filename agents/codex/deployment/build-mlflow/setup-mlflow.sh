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
name = '${experiment_name}'
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
exp = mlflow.get_experiment_by_name('${experiment_name}')
if not exp:
    print('[mlflow-setup] ERROR: experiment not found', file=sys.stderr)
    sys.exit(1)
print(exp.experiment_id)
" 2>/dev/null) || { log_warn "Could not resolve experiment ID for '${experiment_name}' — skipping hook setup"; return; }
        fi

        # Write correct mlflow-tracing.json to CODEX_HOME (user-level)
        cat > "${CODEX_HOME}/mlflow-tracing.json" <<TRACING_JSON
{
  "trackingUri": "${MLFLOW_TRACKING_URI}",
  "experimentId": "${exp_id}"
}
TRACING_JSON
        log_info "mlflow-tracing.json written (experiment ${exp_id})"

        # Ensure notify hook is in user-level config.toml
        if ! grep -q '^notify = ' "${CODEX_HOME}/config.toml" 2>/dev/null; then
            echo '' >> "${CODEX_HOME}/config.toml"
            echo '# MLflow tracing — forwards each Codex turn to MLflow' >> "${CODEX_HOME}/config.toml"
            echo 'notify = ["mlflow-codex", "notify-hook"]' >> "${CODEX_HOME}/config.toml"
            log_info "Notify hook added to user-level config.toml"
        else
            log_info "Notify hook already in config.toml"
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
    else
        log_warn "mlflow-codex not found on PATH"
    fi

    # 4. Write .mlflow-env for interactive oc exec sessions
    cat > "${CODEX_HOME}/.mlflow-env" <<'MLFLOW_ENV'
_sa_token="/var/run/secrets/kubernetes.io/serviceaccount/token"
if [[ -f "${_sa_token}" ]]; then
    export MLFLOW_TRACKING_TOKEN=$(cat "${_sa_token}")
fi
unset _sa_token
MLFLOW_ENV

    # 5. Source from .bashrc for oc exec sessions
    if ! grep -q 'mlflow-env' "${HOME}/.bashrc" 2>/dev/null; then
        echo 'source "${CODEX_HOME}/.mlflow-env" 2>/dev/null || true' >> "${HOME}/.bashrc"
    fi

    log_info "MLflow tracing setup complete"
}

setup_mlflow

if [[ $# -gt 0 ]]; then
    exec "$@"
else
    exec sleep infinity
fi
