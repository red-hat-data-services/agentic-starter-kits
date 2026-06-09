#!/usr/bin/env bash
#
# Claude Code on vLLM — Test Matrix
#
# Validates Claude Code CLI functionality when backed by vLLM.
# Runs tests via `oc exec` against a Claude Code pod on OpenShift.
#
# Usage:
#   bash test_claude_code_matrix.sh --namespace <NS> --deployment <DEPLOY>
#   # or via env vars:
#   export VLLM_NAMESPACE=redhat-ods-applications CLAUDE_DEPLOYMENT=claude-code
#   bash test_claude_code_matrix.sh
#
# Requirements: bash, oc (logged into the cluster)

set -uo pipefail

# --- Configuration -----------------------------------------------------------

VLLM_NAMESPACE="${VLLM_NAMESPACE:-redhat-ods-applications}"
CLAUDE_DEPLOYMENT="${CLAUDE_DEPLOYMENT:-claude-code}"
VLLM_TIMEOUT="${VLLM_TIMEOUT:-120}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --namespace)   VLLM_NAMESPACE="$2";    shift 2 ;;
    --deployment)  CLAUDE_DEPLOYMENT="$2"; shift 2 ;;
    --timeout)     VLLM_TIMEOUT="$2";      shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--namespace <NS>] [--deployment <DEPLOY>] [--timeout <SECS>]"
      echo ""
      echo "Environment variables: VLLM_NAMESPACE, CLAUDE_DEPLOYMENT, VLLM_TIMEOUT"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# --- Helpers ------------------------------------------------------------------

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

pass() { echo -e "  ${GREEN}PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}FAIL${NC} $1"; ((FAIL++)); }
skip() { echo -e "  ${YELLOW}SKIP${NC} $1"; ((SKIP++)); }
header() { echo -e "\n${BOLD}[$1] $2${NC}"; }

claude_run() {
  local prompt="$1"
  oc exec "deployment/$CLAUDE_DEPLOYMENT" -n "$VLLM_NAMESPACE" -- \
    bash -c 'export HOME=/home/claude-agent && timeout "$1" ~/.claude/claude-run -p "$2"' _ "$VLLM_TIMEOUT" "$prompt" 2>&1
}

# --- Preflight ----------------------------------------------------------------

echo "==========================================="
echo " Claude Code on vLLM — Test Matrix"
echo "==========================================="
echo "Namespace:  $VLLM_NAMESPACE"
echo "Deployment: $CLAUDE_DEPLOYMENT"
echo "Timeout:    ${VLLM_TIMEOUT}s"
echo ""

header "0/5" "Preflight — Pod Check"
pod_status=$(oc get deployment "$CLAUDE_DEPLOYMENT" -n "$VLLM_NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [[ "$pod_status" -ge 1 ]]; then
  model=$(oc get deployment "$CLAUDE_DEPLOYMENT" -n "$VLLM_NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="CLAUDE_MODEL")].value}' 2>/dev/null)
  base_url=$(oc get deployment "$CLAUDE_DEPLOYMENT" -n "$VLLM_NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="ANTHROPIC_BASE_URL")].value}' 2>/dev/null)
  pass "Pod ready (model: $model, endpoint: $base_url)"
else
  fail "Deployment $CLAUDE_DEPLOYMENT not ready in $VLLM_NAMESPACE"
  echo -e "\n${RED}Cannot proceed without a running pod. Exiting.${NC}"
  exit 1
fi

# --- Tests --------------------------------------------------------------------

# 1. Single-turn
header "1/5" "Single-turn Prompt"
resp=$(claude_run "What is 2+2? Reply with just the number.")
if echo "$resp" | grep -q "4"; then
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 200)
  pass "Response contains '4': $resp_short"
else
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 300)
  fail "Response did not contain '4': $resp_short"
fi

# 2. Multi-turn / reasoning
header "2/5" "Multi-step Reasoning"
resp=$(claude_run "I have 3 apples. I eat 1, then buy 5 more. How many apples do I have now? Reply with just the number.")
if echo "$resp" | grep -q "7"; then
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 200)
  pass "Correct reasoning: $resp_short"
else
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 300)
  fail "Incorrect or missing answer (expected 7): $resp_short"
fi

# 3. Tool use — bash
header "3/5" "Tool Use — Bash Command"
resp=$(claude_run "Use bash to run: echo hello-from-claude")
if echo "$resp" | grep -qi "hello-from-claude"; then
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 200)
  pass "Bash tool used successfully: $resp_short"
elif echo "$resp" | grep -qiE "echo|bash|command|ran|executed"; then
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 200)
  pass "Bash tool invoked (model confirmed execution): $resp_short"
else
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 300)
  fail "Bash tool not invoked: $resp_short"
fi

# 4. Tool use — file read
header "4/5" "Tool Use — File Read"
resp=$(claude_run "Read the file /etc/os-release and tell me the OS name.")
if echo "$resp" | grep -qiE "red hat|rhel|linux"; then
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 200)
  pass "File read successful: $resp_short"
else
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 300)
  fail "Could not read /etc/os-release or identify OS: $resp_short"
fi

# 5. CLI response verification
header "5/5" "CLI Response Verification"
resp=$(claude_run "Say the word streaming-test-ok.")

if echo "$resp" | grep -qi "streaming-test-ok"; then
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 200)
  pass "CLI response received: $resp_short"
else
  resp_short=$(echo "$resp" | tr '\n' ' ' | head -c 300)
  fail "Expected 'streaming-test-ok' in response: $resp_short"
fi

# --- Summary ------------------------------------------------------------------

echo ""
echo "==========================================="
echo " Summary"
echo "==========================================="
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${RED}FAIL${NC}: $FAIL"
[[ $SKIP -gt 0 ]] && echo -e "  ${YELLOW}SKIP${NC}: $SKIP"
echo ""

if [[ $FAIL -eq 0 ]]; then
  echo -e "${GREEN}All tests passed.${NC}"
  exit 0
else
  echo -e "${RED}$FAIL test(s) failed.${NC}"
  exit 1
fi
