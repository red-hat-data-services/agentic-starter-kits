#!/usr/bin/env bash
#
# End-to-end EvalHub walkthrough — runs all five agent profiles.
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
MLFLOW_INSECURE_TLS="${MLFLOW_INSECURE_TLS:-true}"

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
  "agents/langgraph/templates/react_agent/evalhub/tool_use.yaml"
  "agents/vanilla_python/templates/openai_responses_agent/evalhub/tool_use.yaml"
  "agents/autogen/templates/mcp_agent/evalhub/tool_use.yaml"
  "agents/crewai/templates/websearch_agent/evalhub/tool_use.yaml"
  "agents/langgraph/templates/agentic_rag/evalhub/tool_use.yaml"
  "agents/langgraph/templates/react_with_database_memory/evalhub/tool_use.yaml"
  "agents/llamaindex/templates/websearch_agent/evalhub/tool_use.yaml"
  "agents/langflow/templates/simple_tool_calling_agent/evalhub/tool_use.yaml"
  "agents/langgraph/templates/human_in_the_loop/evalhub/tool_use.yaml"
  "agents/google/templates/adk/evalhub/tool_use.yaml"
  "agents/a2a/templates/langgraph_crewai_agent/evalhub/tool_use.yaml"
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

if [[ -z "${AUTOGEN_MCP_AGENT_ROUTE:-}" ]]; then
  AUTOGEN_MCP_AGENT_ROUTE=$(get_route "autogen-mcp-agent" || true)
  [[ -z "${AUTOGEN_MCP_AGENT_ROUTE}" ]] && AUTOGEN_MCP_AGENT_ROUTE=$(get_route_contains "autogen")
  if [[ -n "${AUTOGEN_MCP_AGENT_ROUTE}" ]]; then
    preflight_ok "AutoGen MCP agent route: ${AUTOGEN_MCP_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover autogen_mcp_agent route. Set AUTOGEN_MCP_AGENT_ROUTE manually."
  fi
else
  preflight_ok "AutoGen MCP agent route (override): ${AUTOGEN_MCP_AGENT_ROUTE}"
fi

if [[ -z "${CREWAI_WEBSEARCH_ROUTE:-}" ]]; then
  CREWAI_WEBSEARCH_ROUTE=$(get_route "crewai-websearch-agent" || true)
  [[ -z "${CREWAI_WEBSEARCH_ROUTE}" ]] && CREWAI_WEBSEARCH_ROUTE=$(get_route_contains "crewai")
  if [[ -n "${CREWAI_WEBSEARCH_ROUTE}" ]]; then
    preflight_ok "CrewAI Websearch agent route: ${CREWAI_WEBSEARCH_ROUTE}"
  else
    preflight_fail "Could not discover crewai_websearch_agent route. Set CREWAI_WEBSEARCH_ROUTE manually."
  fi
else
  preflight_ok "CrewAI Websearch agent route (override): ${CREWAI_WEBSEARCH_ROUTE}"
fi

if [[ -z "${AGENTIC_RAG_AGENT_ROUTE:-}" ]]; then
  AGENTIC_RAG_AGENT_ROUTE=$(get_route "langgraph-agentic-rag" || true)
  [[ -z "${AGENTIC_RAG_AGENT_ROUTE}" ]] && AGENTIC_RAG_AGENT_ROUTE=$(get_route "agentic-rag" || true)
  [[ -z "${AGENTIC_RAG_AGENT_ROUTE}" ]] && AGENTIC_RAG_AGENT_ROUTE=$(get_route_contains "agentic-rag")
  if [[ -n "${AGENTIC_RAG_AGENT_ROUTE}" ]]; then
    preflight_ok "Agentic RAG agent route: ${AGENTIC_RAG_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover agentic_rag route. Set AGENTIC_RAG_AGENT_ROUTE manually."
  fi
else
  preflight_ok "Agentic RAG agent route (override): ${AGENTIC_RAG_AGENT_ROUTE}"
fi

if [[ -z "${DB_MEMORY_AGENT_ROUTE:-}" ]]; then
  DB_MEMORY_AGENT_ROUTE=$(get_route "langgraph-db-memory-agent" || true)
  [[ -z "${DB_MEMORY_AGENT_ROUTE}" ]] && DB_MEMORY_AGENT_ROUTE=$(get_route "db-memory-agent" || true)
  [[ -z "${DB_MEMORY_AGENT_ROUTE}" ]] && DB_MEMORY_AGENT_ROUTE=$(get_route_contains "db-memory")
  if [[ -n "${DB_MEMORY_AGENT_ROUTE}" ]]; then
    preflight_ok "DB Memory agent route: ${DB_MEMORY_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover db_memory_agent route. Set DB_MEMORY_AGENT_ROUTE manually."
  fi
else
  preflight_ok "DB Memory agent route (override): ${DB_MEMORY_AGENT_ROUTE}"
fi

if [[ -z "${LLAMAINDEX_WEBSEARCH_ROUTE:-}" ]]; then
  LLAMAINDEX_WEBSEARCH_ROUTE=$(get_route "llamaindex-websearch-agent" || true)
  [[ -z "${LLAMAINDEX_WEBSEARCH_ROUTE}" ]] && LLAMAINDEX_WEBSEARCH_ROUTE=$(get_route_contains "llamaindex")
  if [[ -n "${LLAMAINDEX_WEBSEARCH_ROUTE}" ]]; then
    preflight_ok "LlamaIndex Websearch agent route: ${LLAMAINDEX_WEBSEARCH_ROUTE}"
  else
    preflight_fail "Could not discover llamaindex_websearch_agent route. Set LLAMAINDEX_WEBSEARCH_ROUTE manually."
  fi
else
  preflight_ok "LlamaIndex Websearch agent route (override): ${LLAMAINDEX_WEBSEARCH_ROUTE}"
fi

if [[ -z "${HITL_AGENT_ROUTE:-}" ]]; then
  HITL_AGENT_ROUTE=$(get_route "langgraph-hitl-agent" || true)
  [[ -z "${HITL_AGENT_ROUTE}" ]] && HITL_AGENT_ROUTE=$(get_route_contains "hitl")
  if [[ -n "${HITL_AGENT_ROUTE}" ]]; then
    preflight_ok "HITL agent route: ${HITL_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover hitl_agent route. Set HITL_AGENT_ROUTE manually."
  fi
else
  preflight_ok "HITL agent route (override): ${HITL_AGENT_ROUTE}"
fi

if [[ -z "${GOOGLE_ADK_AGENT_ROUTE:-}" ]]; then
  GOOGLE_ADK_AGENT_ROUTE=$(get_route "google-adk-agent" || true)
  [[ -z "${GOOGLE_ADK_AGENT_ROUTE}" ]] && GOOGLE_ADK_AGENT_ROUTE=$(get_route_contains "google-adk")
  if [[ -n "${GOOGLE_ADK_AGENT_ROUTE}" ]]; then
    preflight_ok "Google ADK agent route: ${GOOGLE_ADK_AGENT_ROUTE}"
  else
    preflight_fail "Could not discover google_adk_agent route. Set GOOGLE_ADK_AGENT_ROUTE manually."
  fi
else
  preflight_ok "Google ADK agent route (override): ${GOOGLE_ADK_AGENT_ROUTE}"
fi

if [[ -z "${A2A_LANGGRAPH_CREWAI_ROUTE:-}" ]]; then
  A2A_LANGGRAPH_CREWAI_ROUTE=$(get_route "a2a-langgraph-agent" || true)
  [[ -z "${A2A_LANGGRAPH_CREWAI_ROUTE}" ]] && A2A_LANGGRAPH_CREWAI_ROUTE=$(get_route_contains "a2a-langgraph")
  if [[ -n "${A2A_LANGGRAPH_CREWAI_ROUTE}" ]]; then
    preflight_ok "A2A LangGraph-CrewAI agent route: ${A2A_LANGGRAPH_CREWAI_ROUTE}"
  else
    preflight_warn "Could not discover a2a_langgraph_crewai route. Set A2A_LANGGRAPH_CREWAI_ROUTE manually."
  fi
else
  preflight_ok "A2A LangGraph-CrewAI agent route (override): ${A2A_LANGGRAPH_CREWAI_ROUTE}"
fi

# Langflow agent route — lives in a separate namespace (langflow-agent)
LANGFLOW_NAMESPACE="${LANGFLOW_NAMESPACE:-langflow-agent}"
if [[ -z "${LANGFLOW_ROUTE:-}" ]]; then
  LANGFLOW_ROUTE=$(oc get route -n "${LANGFLOW_NAMESPACE}" langflow -o jsonpath='{.spec.host}' 2>/dev/null || true)
  if [[ -n "${LANGFLOW_ROUTE}" ]]; then
    preflight_ok "Langflow agent route: ${LANGFLOW_ROUTE}"
  else
    preflight_warn "Could not discover Langflow route in ${LANGFLOW_NAMESPACE}. Set LANGFLOW_ROUTE manually."
  fi
else
  preflight_ok "Langflow agent route (override): ${LANGFLOW_ROUTE}"
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

# Discover the internal MLflow service URL for in-cluster adapter pods.
# The adapter pod cannot reach the external route (SSL cert mismatch) and
# the sidecar proxy doesn't support MLflow API paths.  The EvalHub
# deployment already uses the internal service URL, so we extract it from
# there.
if [[ -z "${MLFLOW_INTERNAL_URI:-}" ]]; then
  _evalhub_mlflow_uri=$(oc get deployment evalhub -n "${OC_NAMESPACE}" \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MLFLOW_TRACKING_URI")].value}' 2>/dev/null || true)
  if [[ -n "${_evalhub_mlflow_uri}" ]]; then
    # Strip any path suffix (e.g. /mlflow) — the EvalHub Go code uses it for
    # its own routing, but the Python MLflow SDK appends /api/... to the base.
    MLFLOW_INTERNAL_URI=$(python3 -c "from urllib.parse import urlparse, urlunparse; u=urlparse('${_evalhub_mlflow_uri}'); print(urlunparse((u.scheme,u.netloc,'','','','')))")
    preflight_ok "MLflow internal URI (adapter): ${MLFLOW_INTERNAL_URI}"
  else
    preflight_fail "Could not discover internal MLflow URI from EvalHub deployment. Set MLFLOW_INTERNAL_URI manually."
  fi
else
  preflight_ok "MLflow internal URI (override): ${MLFLOW_INTERNAL_URI}"
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

if [[ -n "${AUTOGEN_MCP_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${AUTOGEN_MCP_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "autogen_mcp_agent /health responded"
  else
    preflight_warn "autogen_mcp_agent /health not reachable (https://${AUTOGEN_MCP_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${CREWAI_WEBSEARCH_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${CREWAI_WEBSEARCH_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "crewai_websearch_agent /health responded"
  else
    preflight_warn "crewai_websearch_agent /health not reachable (https://${CREWAI_WEBSEARCH_ROUTE}/health)"
  fi
fi

if [[ -n "${AGENTIC_RAG_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${AGENTIC_RAG_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "agentic_rag /health responded"
  else
    preflight_warn "agentic_rag /health not reachable (https://${AGENTIC_RAG_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${DB_MEMORY_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${DB_MEMORY_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "db_memory_agent /health responded"
  else
    preflight_warn "db_memory_agent /health not reachable (https://${DB_MEMORY_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${LLAMAINDEX_WEBSEARCH_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${LLAMAINDEX_WEBSEARCH_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "llamaindex_websearch_agent /health responded"
  else
    preflight_warn "llamaindex_websearch_agent /health not reachable (https://${LLAMAINDEX_WEBSEARCH_ROUTE}/health)"
  fi
fi

if [[ -n "${HITL_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${HITL_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "hitl_agent /health responded"
  else
    preflight_warn "hitl_agent /health not reachable (https://${HITL_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${GOOGLE_ADK_AGENT_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${GOOGLE_ADK_AGENT_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "google_adk_agent /health responded"
  else
    preflight_warn "google_adk_agent /health not reachable (https://${GOOGLE_ADK_AGENT_ROUTE}/health)"
  fi
fi

if [[ -n "${A2A_LANGGRAPH_CREWAI_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${A2A_LANGGRAPH_CREWAI_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "a2a_langgraph_crewai_agent /health responded"
  else
    preflight_warn "a2a_langgraph_crewai_agent /health not reachable (https://${A2A_LANGGRAPH_CREWAI_ROUTE}/health)"
  fi
fi

if [[ -n "${LANGFLOW_ROUTE:-}" ]]; then
  if curl -sf --max-time 10 "https://${LANGFLOW_ROUTE}/health" > /dev/null 2>&1; then
    preflight_ok "langflow_tool_calling_agent /health responded"
  else
    preflight_warn "langflow_tool_calling_agent /health not reachable (https://${LANGFLOW_ROUTE}/health)"
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

# -- MLflow token resolution ------------------------------------------------
echo "  --- MLflow token ---"
MLFLOW_TOKEN="${MLFLOW_TOKEN:-${OC_TOKEN}}"
if [[ -n "${MLFLOW_TOKEN}" ]]; then
  preflight_ok "Using current OC session token for MLflow auth"
else
  MLFLOW_TOKEN_SECRET="${MLFLOW_TOKEN_SECRET:-langgraph-react-agent-secret}"
  MLFLOW_TOKEN=$(oc get secret -n "${OC_NAMESPACE}" "${MLFLOW_TOKEN_SECRET}" \
    -o jsonpath='{.data.mlflow-tracking-token}' 2>/dev/null | base64 -d 2>/dev/null || true)
  if [[ -n "${MLFLOW_TOKEN}" ]]; then
    preflight_ok "Using token from secret ${MLFLOW_TOKEN_SECRET}"
  fi
fi

if [[ -z "${MLFLOW_TOKEN}" ]]; then
  preflight_fail "Could not resolve MLFLOW_TRACKING_TOKEN (tried oc whoami -t and agent secret)."
fi

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

echo "  Namespace:         ${OC_NAMESPACE}"
echo "  EvalHub:           ${EVALHUB_ROUTE}"
echo "  React agent:       ${REACT_AGENT_ROUTE}"
echo "  OpenAI agent:      ${OPENAI_AGENT_ROUTE}"
echo "  AutoGen MCP agent: ${AUTOGEN_MCP_AGENT_ROUTE}"
echo "  CrewAI Websearch:  ${CREWAI_WEBSEARCH_ROUTE}"
echo "  Agentic RAG agent: ${AGENTIC_RAG_AGENT_ROUTE}"
echo "  DB Memory agent:   ${DB_MEMORY_AGENT_ROUTE}"
echo "  LlamaIndex Websearch: ${LLAMAINDEX_WEBSEARCH_ROUTE}"
echo "  HITL agent:        ${HITL_AGENT_ROUTE}"
echo "  Google ADK agent:  ${GOOGLE_ADK_AGENT_ROUTE}"
echo "  A2A LangGraph-CrewAI: ${A2A_LANGGRAPH_CREWAI_ROUTE:-not discovered}"
echo "  MLflow:            ${MLFLOW_TRACKING_URI}"
echo "  Experiment:        ${MLFLOW_EXPERIMENT}"

# ---------------------------------------------------------------------------
# Step 2 — Build and push the adapter image
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: Building and pushing adapter image ==="

cd "${REPO_ROOT}"
IMAGE_TAG="$(git rev-parse --short HEAD)-$(date +%s)"
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

# JSON-escape the token to prevent injection via special characters
MLFLOW_TOKEN_JSON=$(python3 -c "import json,sys; sys.stdout.write(json.dumps(sys.argv[1]))" "${MLFLOW_TOKEN}")

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
        {"name": "MLFLOW_WORKSPACE", "value": "${OC_NAMESPACE}"},
        {"name": "MLFLOW_TRACE_WAIT_SECONDS", "value": "5"},
        {"name": "MLFLOW_TRACE_MAX_RETRIES", "value": "6"},
        {"name": "MLFLOW_TRACKING_INSECURE_TLS", "value": "true"},
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
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
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
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

cat > "${WORK_DIR}/eval-autogen-mcp-agent.yaml" <<EOF
name: agentic-tool-use-autogen-mcp-agent
description: EvalHub orchestration run for AutoGen MCP agent
model:
  name: autogen-mcp-agent
  url: https://${AUTOGEN_MCP_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["add", "sub"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 60.0
      verify_ssl: true
      fixtures_path: fixtures/autogen_mcp
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

cat > "${WORK_DIR}/eval-crewai-websearch-agent.yaml" <<EOF
name: agentic-tool-use-crewai-websearch-agent
description: EvalHub orchestration run for CrewAI websearch_agent
model:
  name: crewai-websearch-agent
  url: https://${CREWAI_WEBSEARCH_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["Web Search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/crewai_websearch
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-react-agent.yaml"
echo "  Created: eval-openai-responses-agent.yaml"
echo "  Created: eval-autogen-mcp-agent.yaml"
echo "  Created: eval-crewai-websearch-agent.yaml"

cat > "${WORK_DIR}/eval-agentic-rag-agent.yaml" <<EOF
name: agentic-tool-use-agentic-rag-agent
description: EvalHub orchestration run for LangGraph agentic_rag agent
model:
  name: langgraph-agentic-rag-agent
  url: https://${AGENTIC_RAG_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["retriever"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 60.0
      verify_ssl: true
      fixtures_path: fixtures/agentic_rag
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-agentic-rag-agent.yaml"

cat > "${WORK_DIR}/eval-db-memory-agent.yaml" <<EOF
name: agentic-tool-use-db-memory-agent
description: EvalHub orchestration run for LangGraph DB Memory agent
model:
  name: langgraph-db-memory-agent
  url: https://${DB_MEMORY_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/langgraph_db_memory
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-db-memory-agent.yaml"

cat > "${WORK_DIR}/eval-llamaindex-websearch-agent.yaml" <<EOF
name: agentic-tool-use-llamaindex-websearch-agent
description: EvalHub orchestration run for LlamaIndex websearch_agent
model:
  name: llamaindex-websearch-agent
  url: https://${LLAMAINDEX_WEBSEARCH_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["dummy_web_search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/llamaindex_websearch
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-llamaindex-websearch-agent.yaml"

cat > "${WORK_DIR}/eval-hitl-agent.yaml" <<EOF
name: agentic-tool-use-hitl-agent
description: EvalHub orchestration run for LangGraph Human-in-the-Loop agent
model:
  name: langgraph-hitl-agent
  url: https://${HITL_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["create_file"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/langgraph_hitl
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-hitl-agent.yaml"

cat > "${WORK_DIR}/eval-google-adk-agent.yaml" <<EOF
name: agentic-tool-use-google-adk-agent
description: EvalHub orchestration run for Google ADK agent
model:
  name: google-adk-agent
  url: https://${GOOGLE_ADK_AGENT_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["dummy_web_search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 15.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/google_adk
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-google-adk-agent.yaml"

if [[ -n "${A2A_LANGGRAPH_CREWAI_ROUTE:-}" ]]; then
cat > "${WORK_DIR}/eval-a2a-langgraph-crewai-agent.yaml" <<EOF
name: agentic-tool-use-a2a-langgraph-crewai-agent
description: EvalHub orchestration run for A2A LangGraph-CrewAI agent
model:
  name: a2a-langgraph-crewai-agent
  url: https://${A2A_LANGGRAPH_CREWAI_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["ask_crew_specialist", "web_search", "Web Search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 20.0
      timeout_seconds: 60.0
      verify_ssl: true
      fixtures_path: fixtures/a2a_langgraph_crewai
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF

echo "  Created: eval-a2a-langgraph-crewai-agent.yaml"
fi

# Langflow agent — discover flow_id dynamically and obtain auth token
if [[ -n "${LANGFLOW_ROUTE:-}" ]]; then
  LANGFLOW_TOKEN=$(curl -sk --compressed "https://${LANGFLOW_ROUTE}/api/v1/auto_login" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
  LANGFLOW_FLOW_ID="${LANGFLOW_FLOW_ID:-}"
  if [[ -z "${LANGFLOW_FLOW_ID}" ]]; then
    LANGFLOW_FLOW_ID=$(curl -sk --compressed -H "Authorization: Bearer ${LANGFLOW_TOKEN}" \
      "https://${LANGFLOW_ROUTE}/api/v1/flows/" \
      | python3 -c "
import sys, json
flows = json.load(sys.stdin)
if not flows:
    sys.exit(0)
# Prefer exact name match for the outdoor activity agent flow
named = [f for f in flows if 'outdoor' in f.get('name', '').lower() or 'tool' in f.get('name', '').lower()]
if len(named) == 1:
    print(named[0]['id'])
elif len(flows) == 1:
    print(flows[0]['id'])
else:
    names = ', '.join(f'{f[\"name\"]} ({f[\"id\"][:8]})' for f in flows)
    print(f'ERROR: {len(flows)} flows found: {names}. Set LANGFLOW_FLOW_ID explicitly.', file=sys.stderr)
" 2>/dev/null || true)
  fi
  if [[ -z "${LANGFLOW_FLOW_ID}" ]]; then
    preflight_warn "Could not discover Langflow flow_id. Set LANGFLOW_FLOW_ID manually; skipping Langflow eval."
  else
    preflight_ok "Langflow flow_id: ${LANGFLOW_FLOW_ID}"

cat > "${WORK_DIR}/eval-langflow-tool-calling-agent.yaml" <<EOF
name: agentic-tool-use-langflow-tool-calling-agent
description: EvalHub orchestration run for Langflow Simple Tool Calling agent
model:
  name: langflow-tool-calling-agent
  url: https://${LANGFLOW_ROUTE}
benchmarks:
  - id: agentic-tool-use
    provider_id: ${PROVIDER_ID}
    parameters:
      known_tools: ["get_forecast", "search_parks", "get_alerts"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 30.0
      timeout_seconds: 60.0
      verify_ssl: true
      fixtures_path: fixtures/langflow_tool_calling
      api_format: langflow_run
      flow_id: ${LANGFLOW_FLOW_ID}
      mlflow_tracking_uri: ${MLFLOW_INTERNAL_URI}
      mlflow_experiment_name: ${MLFLOW_EXPERIMENT}
      mlflow_trace_experiment_name: ${MLFLOW_AGENT_EXPERIMENT}
EOF
    echo "  Created: eval-langflow-tool-calling-agent.yaml"
  fi
fi

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

echo ""
echo "=== Step 6: Submitting autogen_mcp_agent eval ==="
AUTOGEN_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-autogen-mcp-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${AUTOGEN_OUTPUT}"
AUTOGEN_JOB_ID=$(echo "${AUTOGEN_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting crewai_websearch_agent eval ==="
CREWAI_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-crewai-websearch-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${CREWAI_OUTPUT}"
CREWAI_JOB_ID=$(echo "${CREWAI_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting agentic_rag agent eval ==="
AGENTIC_RAG_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-agentic-rag-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${AGENTIC_RAG_OUTPUT}"
AGENTIC_RAG_JOB_ID=$(echo "${AGENTIC_RAG_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting db_memory_agent eval ==="
DB_MEMORY_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-db-memory-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${DB_MEMORY_OUTPUT}"
DB_MEMORY_JOB_ID=$(echo "${DB_MEMORY_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting llamaindex_websearch_agent eval ==="
LLAMAINDEX_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-llamaindex-websearch-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${LLAMAINDEX_OUTPUT}"
LLAMAINDEX_JOB_ID=$(echo "${LLAMAINDEX_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting hitl_agent eval ==="
HITL_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-hitl-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${HITL_OUTPUT}"
HITL_JOB_ID=$(echo "${HITL_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

echo ""
echo "=== Step 6: Submitting google_adk_agent eval ==="
GOOGLE_ADK_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-google-adk-agent.yaml" --wait --poll-interval 5 2>&1)
echo "${GOOGLE_ADK_OUTPUT}"
GOOGLE_ADK_JOB_ID=$(echo "${GOOGLE_ADK_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)

A2A_LANGGRAPH_CREWAI_JOB_ID=""
if [[ -f "${WORK_DIR}/eval-a2a-langgraph-crewai-agent.yaml" ]]; then
  echo ""
  echo "=== Step 6: Submitting a2a_langgraph_crewai_agent eval ==="
  A2A_LANGGRAPH_CREWAI_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-a2a-langgraph-crewai-agent.yaml" --wait --poll-interval 5 2>&1)
  echo "${A2A_LANGGRAPH_CREWAI_OUTPUT}"
  A2A_LANGGRAPH_CREWAI_JOB_ID=$(echo "${A2A_LANGGRAPH_CREWAI_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)
fi

LANGFLOW_JOB_ID=""
if [[ -f "${WORK_DIR}/eval-langflow-tool-calling-agent.yaml" ]]; then
  echo ""
  echo "=== Step 6: Submitting langflow_tool_calling_agent eval ==="
  LANGFLOW_OUTPUT=$(evalhub eval run --config "${WORK_DIR}/eval-langflow-tool-calling-agent.yaml" --wait --poll-interval 5 2>&1)
  echo "${LANGFLOW_OUTPUT}"
  LANGFLOW_JOB_ID=$(echo "${LANGFLOW_OUTPUT}" | python3 -c "
import sys, re
for line in sys.stdin:
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', line)
    if m:
        print(m.group())
        break
" 2>/dev/null || true)
fi

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
      2>/dev/null || true)
    echo ""
    if [[ -n "${experiment_id}" ]]; then
      echo "  MLflow run: ${MLFLOW_TRACKING_URI}/#/experiments/${experiment_id}/runs/${run_id}?workspace=${OC_NAMESPACE}"
    else
      echo "  MLflow run ${run_id} recorded in experiment '${MLFLOW_EXPERIMENT}' (lookup failed; open MLflow UI and search by experiment name)."
    fi
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
echo ""
print_results "autogen_mcp_agent" "${AUTOGEN_JOB_ID:-}"
echo ""
print_results "crewai_websearch_agent" "${CREWAI_JOB_ID:-}"
echo ""
print_results "agentic_rag_agent" "${AGENTIC_RAG_JOB_ID:-}"
echo ""
print_results "db_memory_agent" "${DB_MEMORY_JOB_ID:-}"
echo ""
print_results "llamaindex_websearch_agent" "${LLAMAINDEX_JOB_ID:-}"
echo ""
print_results "hitl_agent" "${HITL_JOB_ID:-}"
echo ""
print_results "google_adk_agent" "${GOOGLE_ADK_JOB_ID:-}"
if [[ -n "${A2A_LANGGRAPH_CREWAI_JOB_ID:-}" ]]; then
  echo ""
  print_results "a2a_langgraph_crewai_agent" "${A2A_LANGGRAPH_CREWAI_JOB_ID:-}"
fi
if [[ -n "${LANGFLOW_JOB_ID:-}" ]]; then
  echo ""
  print_results "langflow_tool_calling_agent" "${LANGFLOW_JOB_ID:-}"
fi

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
