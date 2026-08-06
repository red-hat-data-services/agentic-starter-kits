#!/usr/bin/env bash
# Wrapper for the @mlflow/codex notify hook that ensures the SA token and
# experiment ID are available regardless of how codex was launched
# (oc exec bypasses .bashrc, so env vars from setup-mlflow.sh are lost).
set -euo pipefail

# Source MLflow env (SA token + experiment ID) written by setup-mlflow.sh
_env="${CODEX_HOME:-/workspace/.codex}/.mlflow-env"
if [[ -f "${_env}" ]]; then
    source "${_env}"
fi

# Fallback: read SA token directly if .mlflow-env wasn't found
_sa_token="/var/run/secrets/kubernetes.io/serviceaccount/token"
if [[ -f "${_sa_token}" ]] && [[ -z "${MLFLOW_TRACKING_TOKEN:-}" ]]; then
    export MLFLOW_TRACKING_TOKEN
    MLFLOW_TRACKING_TOKEN=$(cat "${_sa_token}")
fi

exec mlflow-codex notify-hook "$@"
