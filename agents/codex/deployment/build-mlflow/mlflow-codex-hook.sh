#!/usr/bin/env bash
# Wrapper for the @mlflow/codex notify hook that ensures the SA token is
# available regardless of how codex was launched (oc exec bypasses .bashrc).
set -euo pipefail

_sa_token="/var/run/secrets/kubernetes.io/serviceaccount/token"
if [[ -f "${_sa_token}" ]] && [[ -z "${MLFLOW_TRACKING_TOKEN:-}" ]]; then
    export MLFLOW_TRACKING_TOKEN
    MLFLOW_TRACKING_TOKEN=$(cat "${_sa_token}")
fi

exec mlflow-codex notify-hook "$@"
