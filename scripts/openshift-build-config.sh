#!/usr/bin/env bash
# OpenShift BuildConfig helpers for agent integration tests and local undeploy.
set -euo pipefail

readonly SUCCESSFUL_LIMIT=2
readonly FAILED_LIMIT=1

# Shared cluster resources that must never be deleted by cleanup.
readonly CLEANUP_DENYLIST=(
  postgres
  minio
  mcp-automl
  langflow-simple-tool-calling-agent
)

usage() {
  cat <<EOF
Usage: $(basename "$0") <command> <agent-name> [-n namespace]

Commands:
  patch-history   Set BC history limits to ${SUCCESSFUL_LIMIT}/${FAILED_LIMIT}
  cleanup         Delete BuildConfig and ImageStream for agent-name

Requires: oc logged in; namespace from -n or current oc project.
EOF
}

require_oc() {
  command -v oc >/dev/null 2>&1 || {
    echo "ERROR: oc not found in PATH" >&2
    exit 1
  }
}

is_cleanup_denylisted() {
  local agent="$1"
  local denied
  for denied in "${CLEANUP_DENYLIST[@]}"; do
    if [[ "$agent" == "$denied" ]]; then
      return 0
    fi
  done
  return 1
}

patch_history() {
  local agent="$1"
  local ns_flag=("${NAMESPACE_ARGS[@]}")
  oc patch "bc/${agent}" "${ns_flag[@]}" --type=merge \
    -p "{\"spec\":{\"successfulBuildsHistoryLimit\":${SUCCESSFUL_LIMIT},\"failedBuildsHistoryLimit\":${FAILED_LIMIT}}}" \
    2>/dev/null || true
}

cleanup() {
  local agent="$1"
  local ns_flag=("${NAMESPACE_ARGS[@]}")
  oc delete "buildconfig/${agent}" "imagestream/${agent}" \
    "${ns_flag[@]}" --ignore-not-found=true
}

main() {
  local cmd="${1:-}"
  local agent="${2:-}"
  NAMESPACE_ARGS=()
  if [[ "${3:-}" == "-n" && -n "${4:-}" ]]; then
    NAMESPACE_ARGS=(-n "$4")
  fi

  case "$cmd" in
    patch-history)
      [[ -n "$agent" ]] || { echo "ERROR: agent name required" >&2; usage; exit 1; }
      require_oc
      patch_history "$agent"
      ;;
    cleanup)
      [[ -n "$agent" ]] || { echo "ERROR: agent name required" >&2; usage; exit 1; }
      if is_cleanup_denylisted "$agent"; then
        echo "ERROR: refusing to delete denylisted shared resource: ${agent}" >&2
        exit 1
      fi
      require_oc
      cleanup "$agent"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
