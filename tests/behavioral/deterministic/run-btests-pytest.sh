#!/usr/bin/env bash
# run-btests-pytest.sh — Run behavioral tests for agents in agentic-starter-kits.
#
# Usage:  ./run-btests-pytest.sh                          # run all agents
#         ./run-btests-pytest.sh crewai/websearch_agent    # run one agent
#         ./run-btests-pytest.sh langgraph/react_agent autogen/mcp_agent  # run multiple
#
# Assumes:
#   - Agents are deployed and healthy on OpenShift
#   - MLflow tokens have been refreshed (run deploy-agents --token-only first)
#
# Requirements: oc, uv, curl, jq

set -euo pipefail

# ---------------------------------------------------------------------------
# Cleanup: kill background test processes on exit/interrupt
# ---------------------------------------------------------------------------
CHILD_PIDS=()
cleanup() {
  if [[ ${#CHILD_PIDS[@]} -gt 0 ]]; then
    kill "${CHILD_PIDS[@]}" 2>/dev/null || true
    wait "${CHILD_PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------
# Each entry: "agent_path|url_env_var|deployment_name"
AGENTS=(
  "crewai/templates/websearch_agent|CREWAI_WEBSEARCH_AGENT_URL|crewai-websearch-agent"
  "langgraph/templates/react_agent|REACT_AGENT_URL|langgraph-react-agent"
  "langgraph/templates/agentic_rag|AGENTIC_RAG_AGENT_URL|langgraph-agentic-rag"
  "langgraph/templates/react_with_database_memory|DB_MEMORY_AGENT_URL|langgraph-db-memory-agent"
  "autogen/templates/mcp_agent|AUTOGEN_MCP_AGENT_URL|autogen-mcp-agent"
  "llamaindex/templates/websearch_agent|LLAMAINDEX_WEBSEARCH_AGENT_URL|llamaindex-websearch-agent"
  "vanilla_python/templates/openai_responses_agent|VANILLA_PYTHON_AGENT_URL|openai-responses-agent"
  "langgraph/templates/human_in_the_loop|HITL_AGENT_URL|langgraph-hitl-agent"
  "google/templates/adk|GOOGLE_ADK_AGENT_URL|google-adk-agent"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="${REPO_ROOT}/btest-results/${TIMESTAMP}"

# Result arrays (top-level for bash 3.2 compat — declare -g requires 4.2+)
RESULT_AGENTS=()
RESULT_PASSED=()
RESULT_FAILED=()
RESULT_SKIPPED=()
RESULT_ERRORS=()
RESULT_STATUS=()
RESULT_EXIT_CODES=()

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${RESET} $*"; }
ok()   { echo -e "${GREEN}[$(date +%H:%M:%S)] [OK]${RESET} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] [WARN]${RESET} $*"; }
fail() { echo -e "${RED}[$(date +%H:%M:%S)] [FAIL]${RESET} $*"; }
die()  { fail "$@"; exit 1; }

separator() {
  echo -e "${BOLD}$(printf '=%.0s' {1..80})${RESET}"
}

# Parse IFS-separated agent tuple
agent_path()      { echo "$1" | cut -d'|' -f1; }
agent_env_var()   { echo "$1" | cut -d'|' -f2; }
agent_deploy()    { echo "$1" | cut -d'|' -f3; }

# Parse pytest summary line.  Expected format:
#   "= N passed, M failed, K skipped, J error in Xs ="
#   or any subset thereof.
parse_pytest_summary() {
  local logfile="$1"
  local passed=0 failed=0 skipped=0 errors=0

  # Grab the last short test summary line (the "= ... =" line)
  local summary_line
  summary_line=$(grep -E '^=+.*=+$' "$logfile" | tail -1 || true)

  if [[ -z "$summary_line" ]]; then
    echo "0|0|0|0|NO_SUMMARY"
    return
  fi

  passed=$(echo "$summary_line"  | grep -oE '[0-9]+ passed'  | head -1 | grep -oE '[0-9]+' || echo 0)
  failed=$(echo "$summary_line"  | grep -oE '[0-9]+ failed'  | head -1 | grep -oE '[0-9]+' || echo 0)
  skipped=$(echo "$summary_line" | grep -oE '[0-9]+ skipped' | head -1 | grep -oE '[0-9]+' || echo 0)
  errors=$(echo "$summary_line"  | grep -oE '[0-9]+ errors?' | head -1 | grep -oE '[0-9]+' || echo 0)

  [[ -z "$passed" ]]  && passed=0
  [[ -z "$failed" ]]  && failed=0
  [[ -z "$skipped" ]] && skipped=0
  [[ -z "$errors" ]]  && errors=0

  echo "${passed}|${failed}|${skipped}|${errors}|OK"
}

# ---------------------------------------------------------------------------
# Phase 1: Pre-flight checks
# ---------------------------------------------------------------------------
preflight() {
  separator
  log "${BOLD}Phase 1: Pre-flight checks${RESET}"
  separator

  # oc auth
  log "Checking oc authentication..."
  if ! timeout 30 oc whoami >/dev/null 2>&1; then
    die "Not logged into OpenShift. Run 'oc login' first."
  fi
  OC_USER=$(timeout 30 oc whoami)
  ok "Logged in as: ${OC_USER}"

  # Namespace
  NAMESPACE=$(timeout 30 oc project -q)
  ok "Namespace: ${NAMESPACE}"

  # uv
  log "Checking uv..."
  if ! command -v uv >/dev/null 2>&1; then
    die "'uv' not found in PATH. Install it: https://docs.astral.sh/uv/"
  fi
  ok "uv found: $(uv --version 2>/dev/null || echo 'unknown version')"

  # Validate AGENTS env vars match conftest._AGENT_URL_MAP
  log "Validating agent config against conftest..."
  local conftest_vars
  conftest_vars=$(uv run python -c "
import sys, importlib.util
spec = importlib.util.spec_from_file_location('conftest', '${REPO_ROOT}/tests/behavioral/conftest.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['conftest'] = mod
spec.loader.exec_module(mod)
for v in mod._AGENT_URL_MAP.values():
    print(v)
" 2>/dev/null || true)

  if [[ -n "$conftest_vars" ]]; then
    local script_vars=""
    for agent_tuple in "${AGENTS[@]}"; do
      script_vars+="$(agent_env_var "$agent_tuple")"$'\n'
    done
    local missing=""
    while IFS= read -r var; do
      if ! echo "$script_vars" | grep -qF "$var"; then
        missing+="  $var"$'\n'
      fi
    done <<< "$conftest_vars"
    if [[ -n "$missing" ]]; then
      die "$(printf 'AGENTS array is out of sync with conftest._AGENT_URL_MAP:\n%s' "$missing")"
    else
      ok "AGENTS array in sync with conftest._AGENT_URL_MAP"
    fi
  else
    warn "Could not validate against conftest (uv run python import failed)"
  fi

  # Cluster domain — detect from any route in the namespace
  log "Detecting cluster domain..."
  CLUSTER_DOMAIN=$(timeout 30 oc get routes -n "${NAMESPACE}" -o jsonpath='{.items[0].spec.host}' 2>/dev/null \
    | sed 's/^[^.]*\.//' || true)
  if [[ -z "$CLUSTER_DOMAIN" ]]; then
    die "Could not detect cluster domain from routes in namespace '${NAMESPACE}'."
  fi
  ok "Cluster domain: ${CLUSTER_DOMAIN}"

  # Verify each agent deployment exists and is healthy
  log "Checking agent deployments..."
  local all_healthy=true
  for agent_tuple in "${AGENTS[@]}"; do
    local deploy
    deploy=$(agent_deploy "$agent_tuple")
    local path
    path=$(agent_path "$agent_tuple")

    if ! timeout 30 oc get deployment "${deploy}" -n "${NAMESPACE}" >/dev/null 2>&1; then
      fail "Deployment '${deploy}' not found for agent '${path}'"
      all_healthy=false
      continue
    fi

    # Check ready replicas
    local ready
    ready=$(timeout 30 oc get deployment "${deploy}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "${ready:-0}" -lt 1 ]]; then
      warn "Deployment '${deploy}' has 0 ready replicas"
      all_healthy=false
    else
      ok "Deployment '${deploy}' — ${ready} ready replica(s)"
    fi
  done

  if [[ "$all_healthy" != "true" ]]; then
    warn "Some deployments are missing or unhealthy. Tests for those agents may fail."
  fi

  echo ""
}


# ---------------------------------------------------------------------------
# Phase 2: Detect MLflow config from an existing deployment
# ---------------------------------------------------------------------------
detect_mlflow_config() {
  separator
  log "${BOLD}Phase 2: Detecting MLflow configuration${RESET}"
  separator

  # Use the first available agent deployment to extract MLflow env vars
  local deploy_json=""
  for agent_tuple in "${AGENTS[@]}"; do
    local deploy
    deploy=$(agent_deploy "$agent_tuple")
    deploy_json=$(timeout 30 oc get deployment "${deploy}" -n "${NAMESPACE}" -o json 2>/dev/null || true)
    if [[ -n "$deploy_json" ]]; then
      log "Using deployment '${deploy}' for MLflow config detection"
      break
    fi
  done

  if [[ -z "$deploy_json" ]]; then
    die "No agent deployments found. Cannot detect MLflow configuration."
  fi

  # Extract env vars from the deployment
  MLFLOW_TRACKING_URI=$(echo "$deploy_json" \
    | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="MLFLOW_TRACKING_URI") | .value // empty' 2>/dev/null || true)
  MLFLOW_EXPERIMENT_NAME=$(echo "$deploy_json" \
    | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="MLFLOW_EXPERIMENT_NAME") | .value // empty' 2>/dev/null || true)
  MLFLOW_WORKSPACE=$(echo "$deploy_json" \
    | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="MLFLOW_WORKSPACE") | .value // empty' 2>/dev/null || true)

  # Fallback for workspace
  if [[ -z "$MLFLOW_WORKSPACE" ]]; then
    MLFLOW_WORKSPACE="${NAMESPACE}"
  fi

  # Fresh token
  MLFLOW_TRACKING_TOKEN=$(timeout 30 oc whoami -t)

  if [[ -z "$MLFLOW_TRACKING_URI" ]]; then
    warn "MLFLOW_TRACKING_URI not found in deployment env vars."
  else
    ok "MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI}"
  fi
  if [[ -z "$MLFLOW_EXPERIMENT_NAME" ]]; then
    warn "MLFLOW_EXPERIMENT_NAME not found in deployment env vars."
  else
    ok "MLFLOW_EXPERIMENT_NAME=${MLFLOW_EXPERIMENT_NAME}"
  fi
  ok "MLFLOW_WORKSPACE=${MLFLOW_WORKSPACE}"
  ok "MLFLOW_TRACKING_TOKEN=(refreshed from oc whoami -t)"
  ok "MLFLOW_TRACKING_INSECURE_TLS=true"

  echo ""
}

# ---------------------------------------------------------------------------
# Phase 3: Run tests
# ---------------------------------------------------------------------------
run_tests() {
  separator
  log "${BOLD}Phase 3: Running behavioral tests${RESET}"
  separator

  mkdir -p "${RESULTS_DIR}"
  log "Results directory: ${RESULTS_DIR}"
  echo ""

  # Launch all agents in parallel
  CHILD_PIDS=()
  local pid_to_agent=()

  for agent_tuple in "${AGENTS[@]}"; do
    local path env_var deploy
    path=$(agent_path "$agent_tuple")
    env_var=$(agent_env_var "$agent_tuple")
    deploy=$(agent_deploy "$agent_tuple")

    local route_host
    route_host=$(timeout 30 oc get route "${deploy}" -n "${NAMESPACE}" \
      -o jsonpath='{.spec.host}' 2>/dev/null || true)

    if [[ -z "$route_host" ]]; then
      warn "No route found for '${deploy}'. Skipping ${path}."
      echo "NO_ROUTE" > "${RESULTS_DIR}/$(echo "$path" | tr '/' '_').exit"
      continue
    fi

    local agent_url="https://${route_host}"
    local test_path="agents/${path}/tests/behavioral/"

    if [[ ! -d "${REPO_ROOT}/${test_path}" ]]; then
      warn "Test directory not found: ${test_path}. Skipping."
      echo "NO_TESTS" > "${RESULTS_DIR}/$(echo "$path" | tr '/' '_').exit"
      continue
    fi

    local log_name
    log_name=$(echo "$path" | tr '/' '_')
    local logfile="${RESULTS_DIR}/${log_name}.log"
    local exitfile="${RESULTS_DIR}/${log_name}.exit"

    log "Launching: ${BOLD}${path}${RESET} -> ${logfile}"

    (
      set -euo pipefail
      cd "${REPO_ROOT}"
      export "${env_var}=${agent_url}"
      export MLFLOW_TRACKING_URI="${MLFLOW_TRACKING_URI:-}"
      export MLFLOW_EXPERIMENT_NAME="${MLFLOW_EXPERIMENT_NAME:-}"
      export MLFLOW_TRACKING_TOKEN="${MLFLOW_TRACKING_TOKEN:-}"
      export MLFLOW_WORKSPACE="${MLFLOW_WORKSPACE:-}"
      export MLFLOW_TRACKING_INSECURE_TLS="true"

      uv run --extra test python -m pytest "${test_path}" -v --tb=short
    ) > "${logfile}" 2>&1 &
    local pid=$!
    CHILD_PIDS+=("$pid")
    pid_to_agent+=("${pid}:${path}")
  done

  log "All ${#CHILD_PIDS[@]} test suites launched. Waiting for completion..."
  echo ""

  # Wait for all and capture exit codes
  for entry in "${pid_to_agent[@]}"; do
    local pid="${entry%%:*}"
    local path="${entry#*:}"
    local log_name
    log_name=$(echo "$path" | tr '/' '_')
    local exitfile="${RESULTS_DIR}/${log_name}.exit"

    local exit_code=0
    wait "$pid" || exit_code=$?
    echo "$exit_code" > "$exitfile"

    if [[ "$exit_code" -eq 0 ]]; then
      ok "Finished: ${path} — PASSED"
    else
      fail "Finished: ${path} — FAILED (exit code: ${exit_code})"
    fi
  done

  echo ""
  log "All tests complete. Collecting results..."
  echo ""

  # Collect results from log files
  for agent_tuple in "${AGENTS[@]}"; do
    local path
    path=$(agent_path "$agent_tuple")
    local log_name
    log_name=$(echo "$path" | tr '/' '_')
    local logfile="${RESULTS_DIR}/${log_name}.log"
    local exitfile="${RESULTS_DIR}/${log_name}.exit"

    RESULT_AGENTS+=("$path")

    if [[ ! -f "$exitfile" ]]; then
      RESULT_PASSED+=(0); RESULT_FAILED+=(0); RESULT_SKIPPED+=(0); RESULT_ERRORS+=(0)
      RESULT_STATUS+=("SKIPPED"); RESULT_EXIT_CODES+=(1)
      continue
    fi

    local exit_status
    exit_status=$(cat "$exitfile")

    if [[ "$exit_status" == "NO_ROUTE" || "$exit_status" == "NO_TESTS" ]]; then
      RESULT_PASSED+=(0); RESULT_FAILED+=(0); RESULT_SKIPPED+=(0); RESULT_ERRORS+=(0)
      RESULT_STATUS+=("$exit_status"); RESULT_EXIT_CODES+=(1)
      continue
    fi

    local parsed
    parsed=$(parse_pytest_summary "$logfile")
    local p f s e
    p=$(echo "$parsed" | cut -d'|' -f1)
    f=$(echo "$parsed" | cut -d'|' -f2)
    s=$(echo "$parsed" | cut -d'|' -f3)
    e=$(echo "$parsed" | cut -d'|' -f4)

    RESULT_PASSED+=("$p"); RESULT_FAILED+=("$f"); RESULT_SKIPPED+=("$s"); RESULT_ERRORS+=("$e")
    RESULT_EXIT_CODES+=("$exit_status")

    if [[ "$exit_status" -eq 0 ]]; then
      RESULT_STATUS+=("PASS")
    else
      RESULT_STATUS+=("FAIL")
    fi
  done
}

# ---------------------------------------------------------------------------
# Per-agent detailed breakdown
# ---------------------------------------------------------------------------
print_agent_detail() {
  local path="$1"
  local logfile="$2"
  local status="$3"

  if [[ "$status" == "NO_ROUTE" || "$status" == "NO_TESTS" || "$status" == "SKIPPED" ]]; then
    echo -e "  ${YELLOW}Reason: ${status}${RESET}"
    return
  fi

  if [[ ! -f "$logfile" ]]; then
    echo -e "  ${YELLOW}No log file found${RESET}"
    return
  fi

  # --- MLflow enrichment status ---
  local enrichment_failures
  enrichment_failures=$(grep "MLflow trace enrichment failed\|no trace found" "$logfile" 2>/dev/null | wc -l | tr -d '[:space:]' || true)
  enrichment_failures=${enrichment_failures:-0}
  local tool_calls_not_exposed
  tool_calls_not_exposed=$(grep "tool_calls not exposed" "$logfile" 2>/dev/null | wc -l | tr -d '[:space:]' || true)
  tool_calls_not_exposed=${tool_calls_not_exposed:-0}
  local enrichment_ok=true

  echo -e "  ${BOLD}MLflow Trace Enrichment:${RESET}"
  if [[ "$enrichment_failures" -gt 0 ]]; then
    echo -e "    ${RED}Enrichment failures: ${enrichment_failures} (traces not found after retries)${RESET}"
    enrichment_ok=false
  fi
  if [[ "$tool_calls_not_exposed" -gt 0 ]]; then
    echo -e "    ${YELLOW}tool_calls not exposed warnings: ${tool_calls_not_exposed} (fell back to content heuristics)${RESET}"
    enrichment_ok=false
  fi
  if [[ "$enrichment_ok" == "true" ]]; then
    echo -e "    ${GREEN}All requests enriched with MLflow trace data${RESET}"
  fi

  # --- Tool call detection ---
  echo -e "  ${BOLD}Tool Call Detection:${RESET}"
  local tool_selection_details
  tool_selection_details=$(grep "Tool selection failed:" "$logfile" 2>/dev/null || true)
  local hallucinated_details
  hallucinated_details=$(grep "Hallucinated tools detected:" "$logfile" 2>/dev/null || true)

  if [[ -n "$tool_selection_details" ]]; then
    while IFS= read -r line; do
      local expected actual
      expected=$(echo "$line" | grep -oE "expected \[[^]]*\]" | head -1 || true)
      actual=$(echo "$line" | grep -oE "'actual': \[[^]]*\]" | head -1 || true)
      local missing
      missing=$(echo "$line" | grep -oE "'missing': \[[^]]*\]" | head -1 || true)
      local extra
      extra=$(echo "$line" | grep -oE "'extra': \[[^]]*\]" | head -1 || true)
      echo -e "    ${RED}Mismatch: ${expected} — ${actual}${RESET}"
      if [[ -n "$missing" ]]; then
        echo -e "      ${missing}, ${extra}"
      fi
    done <<< "$tool_selection_details"
  fi

  if [[ -n "$hallucinated_details" ]]; then
    while IFS= read -r line; do
      local tools
      tools=$(echo "$line" | grep -oE "\[.*\]" | head -1 || true)
      echo -e "    ${RED}Hallucinated tools: ${tools}${RESET}"
    done <<< "$hallucinated_details"
  fi

  if [[ -z "$tool_selection_details" && -z "$hallucinated_details" ]]; then
    echo -e "    ${GREEN}No tool name mismatches${RESET}"
  fi

  # --- Failed tests with reasons ---
  local failed_tests
  failed_tests=$(grep "^FAILED " "$logfile" 2>/dev/null || true)
  if [[ -n "$failed_tests" ]]; then
    echo -e "  ${BOLD}Failed Tests:${RESET}"
    while IFS= read -r line; do
      local test_id
      test_id=$(echo "$line" | sed 's/^FAILED //')
      local test_name
      test_name=$(echo "$test_id" | sed 's|.*/||')
      echo -e "    ${RED}x ${test_name}${RESET}"

      # Extract the assertion message for this test
      local assertion_msg
      assertion_msg=$(grep -A1 "^E.*Assertion" "$logfile" 2>/dev/null \
        | grep -v "^--$" | head -20 || true)
    done <<< "$failed_tests"

    # Print unique assertion reasons (deduplicated)
    echo -e "  ${BOLD}Failure Reasons:${RESET}"
    { grep "^E   Assertion" "$logfile" 2>/dev/null || true; } | sort -u | while IFS= read -r line; do
      local reason
      reason=$(echo "$line" | sed 's/^E   AssertionError: //' | sed 's/^E   AssertionError//')
      if [[ -n "$reason" ]]; then
        echo -e "    ${YELLOW}- ${reason}${RESET}"
      fi
    done

    # Check for empty responses
    local empty_count
    empty_count=$(grep "empty response\|Response: $" "$logfile" 2>/dev/null | wc -l | tr -d '[:space:]' || true)
    empty_count=${empty_count:-0}
    if [[ "$empty_count" -gt 0 ]]; then
      echo -e "    ${RED}Agent returned empty responses in ${empty_count} test(s) — agent may be broken${RESET}"
    fi
  fi

  # --- Skipped tests with reasons ---
  local skipped_tests
  skipped_tests=$(grep "SKIPPED" "$logfile" 2>/dev/null | grep -E "^\S" || true)
  if [[ -n "$skipped_tests" ]]; then
    echo -e "  ${BOLD}Skipped Tests:${RESET}"
    while IFS= read -r line; do
      local test_name
      test_name=$(echo "$line" | sed 's|.*/||' | sed 's/ SKIPPED.*//')
      echo -e "    ${YELLOW}~ ${test_name}${RESET}"
    done <<< "$skipped_tests"

    # Extract skip reasons
    local skip_reasons
    skip_reasons=$(grep -E "pytest\.skip\|SKIPPED.*tool_calls not exposed\|cannot (compare|verify)" "$logfile" 2>/dev/null || true)
    if [[ -n "$skip_reasons" ]]; then
      echo -e "    ${YELLOW}Reason: tool_calls not available — requires MLflow trace enrichment${RESET}"
    fi
  fi

  # --- Latency issues ---
  local latency_fail
  latency_fail=$(grep "Latency exceeded" "$logfile" 2>/dev/null || true)
  if [[ -n "$latency_fail" ]]; then
    echo -e "  ${BOLD}Latency:${RESET}"
    echo "$latency_fail" | while IFS= read -r line; do
      local detail
      detail=$(echo "$line" | sed 's/^E   AssertionError: //')
      echo -e "    ${YELLOW}${detail}${RESET}"
    done
  fi

  # --- Streaming parity ---
  local stream_fail
  stream_fail=$(grep "Tool sets differ\|Tool calls differ" "$logfile" 2>/dev/null || true)
  if [[ -n "$stream_fail" ]]; then
    echo -e "  ${BOLD}Streaming Parity:${RESET}"
    echo "$stream_fail" | while IFS= read -r line; do
      local detail
      detail=$(echo "$line" | sed 's/^E   AssertionError: //')
      echo -e "    ${YELLOW}${detail}${RESET}"
    done
  fi

  # --- Pass@k details ---
  local passk_fail
  passk_fail=$(grep "pass@" "$logfile" 2>/dev/null | grep "Assertion" || true)
  if [[ -n "$passk_fail" ]]; then
    echo -e "  ${BOLD}Reliability (pass@k):${RESET}"
    echo "$passk_fail" | sort -u | while IFS= read -r line; do
      local detail
      detail=$(echo "$line" | sed 's/^E   AssertionError: //')
      echo -e "    ${YELLOW}${detail}${RESET}"
    done
  fi
}

# ---------------------------------------------------------------------------
# Phase 4: Summary report
# ---------------------------------------------------------------------------
print_summary() {
  separator
  log "${BOLD}Phase 4: Summary Report${RESET}"
  separator

  echo ""
  echo -e "${BOLD}Results directory:${RESET} ${RESULTS_DIR}"
  echo ""

  # --- Summary table ---
  echo -ne "${BOLD}"
  printf "%-42s  %-8s  %6s  %6s  %7s  %6s\n" \
    "Agent" "Status" "Passed" "Failed" "Skipped" "Errors"
  echo -ne "${RESET}"
  printf '%.0s-' {1..80}
  echo ""

  local overall_pass=true
  local total_passed=0 total_failed=0 total_skipped=0 total_errors=0

  for i in "${!RESULT_AGENTS[@]}"; do
    local status="${RESULT_STATUS[$i]}"
    local color="$GREEN"
    if [[ "$status" == "FAIL" || "$status" == "NO_ROUTE" || "$status" == "NO_TESTS" ]]; then
      color="$RED"
      overall_pass=false
    fi

    echo -ne "${color}"
    printf "%-42s  %-8s  %6s  %6s  %7s  %6s\n" \
      "${RESULT_AGENTS[$i]}" \
      "${status}" \
      "${RESULT_PASSED[$i]}" \
      "${RESULT_FAILED[$i]}" \
      "${RESULT_SKIPPED[$i]}" \
      "${RESULT_ERRORS[$i]}"
    echo -ne "${RESET}"

    total_passed=$((total_passed + RESULT_PASSED[$i]))
    total_failed=$((total_failed + RESULT_FAILED[$i]))
    total_skipped=$((total_skipped + RESULT_SKIPPED[$i]))
    total_errors=$((total_errors + RESULT_ERRORS[$i]))
  done

  printf '%.0s-' {1..80}
  echo ""
  echo -ne "${BOLD}"
  printf "%-42s  %-8s  %6s  %6s  %7s  %6s\n" \
    "TOTAL" "" "$total_passed" "$total_failed" "$total_skipped" "$total_errors"
  echo -ne "${RESET}"
  echo ""

  # --- Detailed breakdown per agent ---
  separator
  log "${BOLD}Detailed Breakdown${RESET}"
  separator

  for i in "${!RESULT_AGENTS[@]}"; do
    local path="${RESULT_AGENTS[$i]}"
    local status="${RESULT_STATUS[$i]}"
    local log_name
    log_name=$(echo "$path" | tr '/' '_')
    local logfile="${RESULTS_DIR}/${log_name}.log"

    echo ""
    if [[ "$status" == "PASS" ]]; then
      echo -e "${GREEN}${BOLD}[PASS] ${path}${RESET}  (${RESULT_PASSED[$i]} passed, ${RESULT_FAILED[$i]} failed, ${RESULT_SKIPPED[$i]} skipped)"
    else
      echo -e "${RED}${BOLD}[FAIL] ${path}${RESET}  (${RESULT_PASSED[$i]} passed, ${RESULT_FAILED[$i]} failed, ${RESULT_SKIPPED[$i]} skipped)"
    fi

    print_agent_detail "$path" "$logfile" "$status"
  done

  echo ""
  separator

  if [[ "$overall_pass" == "true" ]]; then
    echo -e "${GREEN}${BOLD}ALL AGENTS PASSED${RESET}"
  else
    echo -e "${RED}${BOLD}SOME AGENTS FAILED${RESET}"
  fi

  echo ""
  log "Full logs: ${RESULTS_DIR}"
  echo ""

  if [[ "$overall_pass" == "true" ]]; then
    exit 0
  else
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  # Filter agents if paths provided as arguments
  if [[ $# -gt 0 ]]; then
    local filtered=()
    for arg in "$@"; do
      local found=false
      for agent_tuple in "${AGENTS[@]}"; do
        if [[ "$(agent_path "$agent_tuple")" == "$arg" ]]; then
          filtered+=("$agent_tuple")
          found=true
          break
        fi
      done
      if [[ "$found" == "false" ]]; then
        echo -e "${RED}Unknown agent: ${arg}${RESET}"
        echo "Available agents:"
        for agent_tuple in "${AGENTS[@]}"; do
          echo "  $(agent_path "$agent_tuple")"
        done
        exit 1
      fi
    done
    AGENTS=("${filtered[@]}")
  fi

  echo ""
  separator
  log "${BOLD}Behavioral Test Runner — agentic-starter-kits${RESET}"
  log "Timestamp: ${TIMESTAMP}"
  log "Agents: ${#AGENTS[@]}"
  separator
  echo ""

  preflight
  detect_mlflow_config
  run_tests
  print_summary
}

main "$@"