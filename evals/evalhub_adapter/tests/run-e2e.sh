#!/usr/bin/env bash
#
# End-to-end EvalHub walkthrough — runs both agent profiles.
# Preflight covers README step 1 (prerequisites); steps 2-7 follow the README.
#
# Cluster: agentic-mcp (ROSA HCP)
# Namespace: adonheis-btest1
#
# Override any value via env vars before running.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REGISTRY_USER="${REGISTRY_USER:-adonheis}"
OC_NAMESPACE="${OC_NAMESPACE:-adonheis-btest1}"
# Default empty — discovered from agent deployment in route discovery phase
MLFLOW_EXPERIMENT="${MLFLOW_EXPERIMENT:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/evalhub-e2e.XXXXXX")
chmod 700 "${WORK_DIR}"
PROVIDER_ID=""

cleanup() {
  local exit_code=$?
  trap - EXIT
  if [[ -n "${PROVIDER_ID:-}" && -n "${EVALHUB_ROUTE:-}" ]]; then
    echo "  Cleaning up provider ${PROVIDER_ID}..."
    curl -s -o /dev/null -X DELETE \
      "https://${EVALHUB_ROUTE}/api/v1/evaluations/providers/${PROVIDER_ID}" \
      -H "Authorization: Bearer ${OC_TOKEN}" \
      -H "X-Tenant: ${OC_NAMESPACE}" || true
  fi
  rm -rf "${WORK_DIR}"
  exit "${exit_code}"
}
trap cleanup EXIT

OC_TOKEN=$(oc whoami -t 2>/dev/null || true)
MLFLOW_INSECURE_TLS="${MLFLOW_INSECURE_TLS:-false}"

PREFLIGHT_PASS=0
PREFLIGHT_WARN=0

preflight_ok()   { echo "  [OK]   $1"; }
preflight_fail() { echo "  [FAIL] $1"; PREFLIGHT_PASS=1; }
preflight_warn() { echo "  [WARN] $1"; PREFLIGHT_WARN=1; }

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
echo "=== Preflight: verifying environment ==="
echo ""

# -- Required CLI tools ----------------------------------------------------
echo "  --- CLI tools ---"
for cmd in oc evalhub podman python3 curl git; do
  if command -v "${cmd}" > /dev/null 2>&1; then
    preflight_ok "${cmd} ($(command -v "${cmd}"))"
  else
    case "${cmd}" in
      evalhub) preflight_fail "${cmd} not found. Run: uv pip install .[evalhub,test-mlflow]" ;;
      *)       preflight_fail "${cmd} not found" ;;
    esac
  fi
done
echo ""

# -- oc authentication & namespace access ----------------------------------
echo "  --- OpenShift auth ---"
if oc whoami > /dev/null 2>&1; then
  preflight_ok "oc login active ($(oc whoami))"
else
  preflight_fail "oc login required (oc whoami failed)"
fi

if oc get namespace "${OC_NAMESPACE}" > /dev/null 2>&1; then
  preflight_ok "namespace ${OC_NAMESPACE} accessible"
else
  preflight_fail "namespace ${OC_NAMESPACE} not found or not accessible"
fi
echo ""

# -- Container registry auth -----------------------------------------------
echo "  --- Container registry ---"
REGISTRY_HOST="quay.io"
if podman login --get-login "${REGISTRY_HOST}" > /dev/null 2>&1; then
  preflight_ok "podman logged in to ${REGISTRY_HOST}"
else
  preflight_fail "podman not logged in to ${REGISTRY_HOST}. Run: podman login ${REGISTRY_HOST}"
fi
echo ""

# -- Required repo files ---------------------------------------------------
echo "  --- Repo files ---"
REQUIRED_FILES=(
  "evals/evalhub_adapter/Containerfile"
  "evals/evalhub_adapter/adapter.py"
  "agents/langgraph/react_agent/evalhub/tool_use.yaml"
  "agents/vanilla_python/openai_responses_agent/evalhub/tool_use.yaml"
)
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "${REPO_ROOT}/${f}" ]]; then
    preflight_ok "${f}"
  else
    preflight_fail "${f} missing"
  fi
done
echo ""

# -- Route discovery -------------------------------------------------------
echo "  --- Route discovery ---"

get_route() {
  local name="$1"
  oc get route -n "${OC_NAMESPACE}" -o jsonpath="{.items[?(@.metadata.name==\"${name}\")].spec.host}" 2>/dev/null || true
}

get_route_contains() {
  local needle="$1"
  oc get route -n "${OC_NAMESPACE}" \
    -o custom-columns=NAME:.metadata.name,HOST:.spec.host --no-headers 2>/dev/null \
    | awk -v needle="${needle}" '$1 ~ needle {print $2; exit}' || true
}

if [[ -z "${EVALHUB_ROUTE:-}" ]]; then
  EVALHUB_ROUTE=$(get_route "evalhub" || get_route "eval-hub" || true)
  [[ -z "${EVALHUB_ROUTE}" ]] && EVALHUB_ROUTE=$(get_route_contains "eval")
  if [[ -n "${EVALHUB_ROUTE}" ]]; then
    preflight_ok "EvalHub route: ${EVALHUB_ROUTE}"
  else
    preflight_fail "Could not discover EvalHub route. Set EVALHUB_ROUTE manually."
  fi
else
  preflight_ok "EvalHub route (override): ${EVALHUB_ROUTE}"
fi

if [[ -z "${REACT_AGENT_ROUTE:-}" ]]; then
  REACT_AGENT_ROUTE=$(get_route "langgraph-react-agent" || true)
  [[ -z "${REACT_AGENT_ROUTE}" ]] && REACT_AGENT_ROUTE=$(get_route "react-agent" || true)
  [[ -z "${REACT_AGENT_ROUTE}" ]] && REACT_AGENT_ROUTE=$(get_route_contains "react")
  if [[ -n "${REACT_AGENT_ROUTE}" ]]; then
    preflight_ok "React agent route: ${REACT_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover react_agent route. Set REACT_AGENT_ROUTE manually."
  fi
else
  preflight_ok "React agent route (override): ${REACT_AGENT_ROUTE}"
fi

if [[ -z "${OPENAI_AGENT_ROUTE:-}" ]]; then
  OPENAI_AGENT_ROUTE=$(get_route "openai-responses-agent" || true)
  [[ -z "${OPENAI_AGENT_ROUTE}" ]] && OPENAI_AGENT_ROUTE=$(get_route_contains "openai")
  if [[ -n "${OPENAI_AGENT_ROUTE}" ]]; then
    preflight_ok "OpenAI agent route: ${OPENAI_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover openai_responses_agent route. Set OPENAI_AGENT_ROUTE manually."
  fi
else
  preflight_ok "OpenAI agent route (override): ${OPENAI_AGENT_ROUTE}"
fi

if [[ -z "${MLFLOW_TRACKING_URI:-}" ]]; then
  MLFLOW_TRACKING_URI=$(oc get deployment -n "${OC_NAMESPACE}" -o jsonpath='{.items[*].spec.template.spec.containers[0].env[?(@.name=="MLFLOW_TRACKING_URI")].value}' 2>/dev/null | awk '{print $1}' || true)
  if [[ -z "${MLFLOW_TRACKING_URI}" ]]; then
    MLFLOW_HOST=$(oc get route -n redhat-ods-applications mlflow -o jsonpath='{.spec.host}' 2>/dev/null || true)
    [[ -n "${MLFLOW_HOST}" ]] && MLFLOW_TRACKING_URI="https://${MLFLOW_HOST}"
  fi
  if [[ -n "${MLFLOW_TRACKING_URI}" ]]; then
    preflight_ok "MLflow URI: ${MLFLOW_TRACKING_URI}"
  else
    preflight_fail "Could not discover MLflow tracking URI. Set MLFLOW_TRACKING_URI manually."
  fi
else
  preflight_ok "MLflow URI (override): ${MLFLOW_TRACKING_URI}"
fi

# Discover agent-side experiment (where agents write traces)
MLFLOW_AGENT_EXPERIMENT=$(oc get deployment -n "${OC_NAMESPACE}" -o jsonpath='{.items[*].spec.template.spec.containers[0].env[?(@.name=="MLFLOW_EXPERIMENT_NAME")].value}' 2>/dev/null | awk '{print $1}' || true)
if [[ -z "${MLFLOW_AGENT_EXPERIMENT}" ]]; then
  MLFLOW_AGENT_EXPERIMENT="${OC_NAMESPACE}"
  preflight_warn "Could not discover MLFLOW_EXPERIMENT_NAME from agents. Defaulting to namespace: ${MLFLOW_AGENT_EXPERIMENT}"
else
  preflight_ok "MLflow agent experiment: ${MLFLOW_AGENT_EXPERIMENT}"
fi

# Run-logging experiment — unique per e2e run so results are isolated
RUN_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex[:5])")
if [[ -z "${MLFLOW_EXPERIMENT}" ]]; then
  MLFLOW_EXPERIMENT="${MLFLOW_AGENT_EXPERIMENT}-eval-${RUN_ID}"
fi
preflight_ok "MLflow run experiment: ${MLFLOW_EXPERIMENT}"
echo ""

# -- Service health checks -------------------------------------------------
echo "  --- Service health ---"

if [[ -n "${REACT_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${REACT_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "react_agent /health responded"
  else
    preflight_warn "react_agent /health not reachable (https://${REACT_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${OPENAI_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${OPENAI_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "openai_responses_agent /health responded"
  else
    preflight_warn "openai_responses_agent /health not reachable (https://${OPENAI_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${EVALHUB_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${EVALHUB_ROUTE}/api/v1/health" > /dev/null 2>&1; then
    preflight_ok "EvalHub API healthy"
  else
    preflight_warn "EvalHub API not reachable (https://${EVALHUB_ROUTE}/api/v1/health)"
  fi
fi

if [[ -n "${MLFLOW_TRACKING_URI:-}" ]]; then
  if curl -sf --max-time 10 "${MLFLOW_TRACKING_URI}/health" > /dev/null 2>&1 \
     || curl -sf --max-time 10 "${MLFLOW_TRACKING_URI}/api/2.0/mlflow/experiments/list?max_results=1" > /dev/null 2>&1; then
    preflight_ok "MLflow reachable"
  else
    preflight_warn "MLflow not reachable (${MLFLOW_TRACKING_URI})"
  fi
fi
echo ""

# -- Preflight summary -----------------------------------------------------
if [[ "${PREFLIGHT_PASS}" -ne 0 ]]; then
  echo "  Preflight FAILED — fix the errors above before continuing."
  exit 1
fi
if [[ "${PREFLIGHT_WARN}" -ne 0 ]]; then
  echo "  Preflight passed with warnings — some services may be unreachable."
else
  echo "  Preflight passed."
fi
echo ""

# ---------------------------------------------------------------------------
# Configuration summary (discovered values before starting)
# ---------------------------------------------------------------------------
echo "=== Configuration ==="

echo "  Namespace:    ${OC_NAMESPACE}"
echo "  EvalHub:      ${EVALHUB_ROUTE}"
echo "  React agent:  ${REACT_AGENT_ROUTE}"
echo "  OpenAI agent: ${OPENAI_AGENT_ROUTE}"
echo "  MLflow:       ${MLFLOW_TRACKING_URI}"
echo "  Experiment:   ${MLFLOW_EXPERIMENT}"

# ---------------------------------------------------------------------------
# Step 2 — Build and push the adapter image
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: Building and pushing adapter image ==="

cd "${REPO_ROOT}"
IMAGE_TAG=$(git rev-parse --short HEAD)
ADAPTER_IMAGE="quay.io/${REGISTRY_USER}/evalhub-agentic-adapter:${IMAGE_TAG}"

echo "  Image: ${ADAPTER_IMAGE}"
podman build -t "${ADAPTER_IMAGE}" -f evals/evalhub_adapter/Containerfile .
podman push "${ADAPTER_IMAGE}"
echo "  Pushed."

# ---------------------------------------------------------------------------
# Step 3 — Configure EvalHub CLI
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: Configuring EvalHub CLI ==="

evalhub config set base_url "https://${EVALHUB_ROUTE}"
evalhub config set token "${OC_TOKEN}"
evalhub config set tenant "${OC_NAMESPACE}"

echo "  Running health check..."
evalhub health

# ---------------------------------------------------------------------------
# Step 4 — Register provider
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: Registering provider ==="

# Resolve MLflow token for the adapter pod.
# EvalHub runtime Env does NOT support secretKeyRef — tokens must be literal values.
# Prefer the current OC session token (always fresh) over the agent secret
# (which may hold an expired token from a previous session).
MLFLOW_TOKEN="${MLFLOW_TOKEN:-${OC_TOKEN}}"
if [[ -n "${MLFLOW_TOKEN}" ]]; then
  echo "  Using current OC session token for MLflow auth"
else
  MLFLOW_TOKEN_SECRET="${MLFLOW_TOKEN_SECRET:-langgraph-react-agent-secret}"
  MLFLOW_TOKEN=$(oc get secret -n "${OC_NAMESPACE}" "${MLFLOW_TOKEN_SECRET}" \
    -o jsonpath='{.data.mlflow-tracking-token}' 2>/dev/null | base64 -d 2>/dev/null || true)
  if [[ -n "${MLFLOW_TOKEN}" ]]; then
    echo "  Using token from secret ${MLFLOW_TOKEN_SECRET}"
  fi
fi

if [[ -z "${MLFLOW_TOKEN}" ]]; then
  preflight_fail "Could not resolve MLFLOW_TRACKING_TOKEN (tried oc whoami -t and agent secret)."
  exit 1
fi

# JSON-escape the token to prevent injection via special characters
MLFLOW_TOKEN_JSON=$(python3 -c "import json,sys; sys.stdout.write(json.dumps(sys.argv[1]))" "${MLFLOW_TOKEN}")

# Validate token against MLflow before registering
CURL_TLS_FLAG=""
if [[ "${MLFLOW_INSECURE_TLS}" == "true" || "${EVALHUB_ALLOW_INSECURE_TLS:-}" == "true" ]]; then
  CURL_TLS_FLAG="-k"
fi
MLFLOW_AUTH_CHECK=$(curl -s ${CURL_TLS_FLAG} -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ${MLFLOW_TOKEN}" \
  "${MLFLOW_TRACKING_URI}/api/2.0/mlflow/experiments/list?max_results=1" 2>/dev/null || true)
if [[ "${MLFLOW_AUTH_CHECK}" == "401" || "${MLFLOW_AUTH_CHECK}" == "403" ]]; then
  preflight_warn "MLflow token appears invalid (HTTP ${MLFLOW_AUTH_CHECK})."
  echo "         Refresh the token: export MLFLOW_TOKEN=\$(oc whoami -t) && re-run"
elif [[ "${MLFLOW_AUTH_CHECK}" != "200" ]]; then
  preflight_warn "MLflow reachability check failed (HTTP ${MLFLOW_AUTH_CHECK})."
  echo "         If mlflow_run_id is null in results, refresh the token:"
  echo "         export MLFLOW_TOKEN=\$(oc whoami -t) && re-run"
fi

cat > "${WORK_DIR}/provider-agentic.json" <<EOF
{
  "name": "Agentic Behavioral Evaluation",
  "title": "Agentic",
  "description": "Behavioral evaluation for agentic-starter-kit agents",
  "tags": ["agentic", "behavioral", "tool-use"],
  "benchmarks": [
    {
      "id": "agentic-tool-use",
      "name": "Agentic Tool Use",
      "description": "Evaluates tool selection and tool-call behavior",
      "category": "agentic",
      "metrics": [
        "tool_selection",
        "tool_sequence",
        "hallucinated_tools",
        "tool_call_validity"
      ],
      "num_few_shot": 0,
      "dataset_size": 5,
      "primary_score": {
        "metric": "tool_selection",
        "lower_is_better": false
      }
    }
  ],
  "runtime": {
    "k8s": {
      "Image": "${ADAPTER_IMAGE}",
      "Entrypoint": ["python", "-m", "evalhub_adapter.adapter"],
      "Env": [
        {"name": "MLFLOW_TRACKING_TOKEN", "value": ${MLFLOW_TOKEN_JSON}},
        {"name": "MLFLOW_TRACKING_INSECURE_TLS", "value": "${MLFLOW_INSECURE_TLS}"},
        {"name": "MLFLOW_WORKSPACE", "value": "${OC_NAMESPACE}"},
        {"name": "EVALHUB_ALLOW_LOCALHOST", "value": "true"}
      ]
    }
  }
}
EOF

echo "  Registering via REST API..."
PROVIDER_RESPONSE=$(curl -s -X POST "https://${EVALHUB_ROUTE}/api/v1/evaluations/providers" \
  -H "Authorization: Bearer ${OC_TOKEN}" \
  -H "X-Tenant: ${OC_NAMESPACE}" \
  -H "Content-Type: application/json" \
  --data @"${WORK_DIR}/provider-agentic.json")

echo "  Provider registered: $(echo "${PROVIDER_RESPONSE}" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    r = d.get('resource', d)
    print(f\"id={r.get('id','?')} name={r.get('name','?')}\")
except: print('(could not parse response)')
" 2>/dev/null)"

PROVIDER_ID=$(echo "${PROVIDER_RESPONSE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('resource',{}).get('id','') or d.get('id',''))" 2>/dev/null || true)
if [[ -z "${PROVIDER_ID}" ]]; then
  echo "  WARNING: Could not extract provider ID from response."
  echo "  Run 'evalhub providers list' and set PROVIDER_ID manually, then re-run."
  evalhub providers list || echo "  (providers list failed — non-fatal)"
  exit 1
fi
echo "  Provider ID: ${PROVIDER_ID}"

evalhub providers list || echo "  (providers list failed — non-fatal, continuing)"

# ---------------------------------------------------------------------------
# Step 5 — Create eval run configs
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 5: Creating eval run configs ==="

cat > "${WORK_DIR}/eval-react-agent.yaml" <<EOF
name: agentic-tool-use-react-agent
description: EvalHub orchestration run for LangGraph react_agent
model:
  name: langgraph-react-agent
  url: https://${REACT_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 8.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/langgraph_react
      mlflow_tracking_uri: ${MLFLOW_TRACKING_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

cat > "${WORK_DIR}/eval-openai-responses-agent.yaml" <<EOF
name: agentic-tool-use-openai-responses-agent
description: EvalHub orchestration run for vanilla_python openai_responses_agent
model:
  name: openai-responses-agent
  url: https://${OPENAI_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["search_price", "search_reviews"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 8.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/vanilla_python
      mlflow_tracking_uri: ${MLFLOW_TRACKING_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-react-agent.yaml"
echo "  Created: eval-openai-responses-agent.yaml"

# ---------------------------------------------------------------------------
# Step 6 — Submit jobs and wait
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 6: Submitting react_agent eval ==="
REACT_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-react-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${REACT_OUTPUT}"
REACT_JOB_ID=$(echo "${REACT_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting openai_responses_agent eval ==="
OPENAI_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-openai-responses-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${OPENAI_OUTPUT}"
OPENAI_JOB_ID=$(echo "${OPENAI_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

# ---------------------------------------------------------------------------
# Step 7 — Check results
# ---------------------------------------------------------------------------
print_results() {
  local label="$1" job_id="$2"
  if [[ -z "${job_id}" ]]; then
    echo "  ${label}: could not extract job ID from submission output"
    return
  fi
  echo "  ${label} (job ${job_id}):"
  local results_json
  results_json=$(evalhub eval results "${job_id}" --format json 2>/dev/null || true)
  echo "${results_json}"

  local run_id
  run_id=$(echo "${results_json}" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    items = d if isinstance(d, list) else [d]
    rid = ''
    for item in items:
        if not isinstance(item, dict):
            continue
        rid = item.get('mlflow_run_id') or ''
        if rid:
            break
    print(rid)
except: print('')
" 2>/dev/null || true)

  if [[ -n "${run_id}" ]]; then
    local encoded_experiment experiment_id
    encoded_experiment=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "${MLFLOW_EXPERIMENT}")
    experiment_id=$(curl -sf --max-time 5 \
      ${CURL_TLS_FLAG} \
      -H "Authorization: Bearer ${MLFLOW_TOKEN}" \
      "${MLFLOW_TRACKING_URI}/api/2.0/mlflow/experiments/get-by-name?experiment_name=${encoded_experiment}" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['experiment']['experiment_id'])" \
      2>/dev/null || echo "${encoded_experiment}")
    echo ""
    echo "  MLflow run: ${MLFLOW_TRACKING_URI}/#/experiments/${experiment_id}/runs/${run_id}?workspace=${OC_NAMESPACE}"
  else
    echo ""
    echo "  MLflow run ID not found in results. Check manually:"
    echo "    evalhub eval results ${job_id} --format json"
  fi
}

echo ""
echo "=== Step 7: Results ==="

evalhub eval status
echo ""
print_results "react_agent" "${REACT_JOB_ID:-}"
echo ""
print_results "openai_responses_agent" "${OPENAI_JOB_ID:-}"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
echo ""
echo "=== Cleanup ==="

if [[ -n "${PROVIDER_ID:-}" ]]; then
  echo "  Deleting provider ${PROVIDER_ID}..."
  DELETE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
    "https://${EVALHUB_ROUTE}/api/v1/evaluations/providers/${PROVIDER_ID}" \
    -H "Authorization: Bearer ${OC_TOKEN}" \
    -H "X-Tenant: ${OC_NAMESPACE}")
  if [[ "${DELETE_STATUS}" =~ ^2 ]]; then
    echo "  Provider deleted."
  else
    echo "  WARNING: Provider deletion returned HTTP ${DELETE_STATUS}."
    echo "  Delete manually: curl -X DELETE \"https://${EVALHUB_ROUTE}/api/v1/evaluations/providers/${PROVIDER_ID}\" -H \"Authorization: Bearer \$(oc whoami -t)\" -H \"X-Tenant: ${OC_NAMESPACE}\""
  fi
  PROVIDER_ID=""
else
  echo "  No provider ID captured — skipping provider cleanup."
fi

echo "  Work directory ${WORK_DIR} will be removed on exit (trap)."
