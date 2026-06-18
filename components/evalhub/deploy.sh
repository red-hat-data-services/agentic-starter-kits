#!/usr/bin/env bash
set -euo pipefail

NS="${1:?Usage: ./deploy.sh <namespace>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVALHUB_IMAGE="${EVALHUB_IMAGE:-quay.io/evalhub/evalhub:0.3.0}"
EVALHUB_CR_PATH="${EVALHUB_CR_PATH:-${SCRIPT_DIR}/evalhub-cr.yaml}"
TRUSTYAI_OPERATOR_NAMESPACE="${TRUSTYAI_OPERATOR_NAMESPACE:-redhat-ods-applications}"
TRUSTYAI_OPERATOR_DEPLOYMENT="${TRUSTYAI_OPERATOR_DEPLOYMENT:-trustyai-service-operator-controller-manager}"
MLFLOW_ROUTE_NAMESPACE="${MLFLOW_ROUTE_NAMESPACE:-redhat-ods-applications}"
DISABLE_OPERATOR_SCALE_DOWN="${DISABLE_OPERATOR_SCALE_DOWN:-false}"
ROLLBACK_ON_FAILURE="${ROLLBACK_ON_FAILURE:-true}"
SKIP_PULL_SECRET="${SKIP_PULL_SECRET:-false}"
PULL_SECRET_NAME="${PULL_SECRET_NAME:-quay-pull-secret}"
EVALHUB_INSECURE_SKIP_VERIFY="${EVALHUB_INSECURE_SKIP_VERIFY:-false}"
ORIGINAL_OPERATOR_REPLICAS=""
ORIGINAL_EVALHUB_IMAGE=""
ORIGINAL_CONFIG_BACKUP=""

cleanup() {
  local exit_code=$?

  if [[ "${exit_code}" -ne 0 ]] && [[ "${ROLLBACK_ON_FAILURE}" == "true" ]]; then
    echo "=== Cleanup: rollback on failure enabled ==="
    local rollback_restart="false"
    if [[ -n "${ORIGINAL_CONFIG_BACKUP}" && -s "${ORIGINAL_CONFIG_BACKUP}" ]]; then
      echo "  Restoring evalhub-config ConfigMap"
      oc create configmap evalhub-config -n "${NS}" \
        --from-file=config.yaml="${ORIGINAL_CONFIG_BACKUP}" --dry-run=client -o yaml | oc apply -f - >/dev/null 2>&1 || true
      rollback_restart="true"
    fi
    if [[ -n "${ORIGINAL_EVALHUB_IMAGE}" ]]; then
      echo "  Restoring evalhub deployment image: ${ORIGINAL_EVALHUB_IMAGE}"
      oc set image deployment/evalhub -n "${NS}" "evalhub=${ORIGINAL_EVALHUB_IMAGE}" >/dev/null 2>&1 || true
      rollback_restart="true"
    fi
    if [[ "${rollback_restart}" == "true" ]]; then
      oc rollout restart deployment/evalhub -n "${NS}" >/dev/null 2>&1 || true
    fi
  fi

  if [[ "${DISABLE_OPERATOR_SCALE_DOWN}" != "true" ]] && [[ -n "${ORIGINAL_OPERATOR_REPLICAS}" ]]; then
    echo "=== Cleanup: restoring TrustyAI operator replicas (${ORIGINAL_OPERATOR_REPLICAS}) ==="
    oc scale deployment "${TRUSTYAI_OPERATOR_DEPLOYMENT}" \
      -n "${TRUSTYAI_OPERATOR_NAMESPACE}" \
      --replicas="${ORIGINAL_OPERATOR_REPLICAS}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${ORIGINAL_CONFIG_BACKUP}" ]]; then
    rm -f "${ORIGINAL_CONFIG_BACKUP}" || true
  fi
  exit "${exit_code}"
}
trap cleanup EXIT

echo "=== Step 1: Verify EvalHub CRD exists ==="
if ! oc get crd evalhubs.trustyai.opendatahub.io > /dev/null 2>&1; then
  echo "ERROR: EvalHub CRD not found."
  echo "  Requires RHOAI 3.4.0-ea.2+ with TrustyAI set to Managed in the DataScienceCluster."
  exit 1
fi
echo "  CRD found."

echo "=== Step 1b: Verify local Python YAML dependency ==="
if ! python3 -c 'import yaml' > /dev/null 2>&1; then
  echo "ERROR: python3 with pyyaml is required to patch evalhub-config."
  exit 1
fi
echo "  python3 + pyyaml available."

echo "=== Step 2: Label namespace for tenant provisioning ==="
oc label namespace "${NS}" evalhub.trustyai.opendatahub.io/tenant=true --overwrite

echo "=== Step 3: Create EvalHub CR ==="
oc apply -n "${NS}" -f "${EVALHUB_CR_PATH}"
echo "  Waiting for EvalHub to be ready..."
for i in $(seq 1 30); do
  PHASE=$(oc get evalhub evalhub -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || true)
  READY=$(oc get evalhub evalhub -n "${NS}" -o jsonpath='{.status.ready}' 2>/dev/null || true)
  if [[ "${PHASE}" == "Ready" && "${READY}" == "True" ]]; then
    echo "  EvalHub CR is ready."
    break
  fi
  sleep 5
done
if [[ "${PHASE:-}" != "Ready" || "${READY:-}" != "True" ]]; then
  echo "ERROR: EvalHub CR did not reach Ready state in time."
  exit 1
fi

echo "=== Step 4: Override EvalHub image to ${EVALHUB_IMAGE} ==="
if [[ "${DISABLE_OPERATOR_SCALE_DOWN}" != "true" ]]; then
  ORIGINAL_OPERATOR_REPLICAS="$(
    oc get deployment "${TRUSTYAI_OPERATOR_DEPLOYMENT}" \
      -n "${TRUSTYAI_OPERATOR_NAMESPACE}" \
      -o jsonpath='{.spec.replicas}' 2>/dev/null || true
  )"
  if [[ -n "${ORIGINAL_OPERATOR_REPLICAS}" ]]; then
    echo "  Scaling down TrustyAI operator to prevent reconciliation..."
    oc scale deployment "${TRUSTYAI_OPERATOR_DEPLOYMENT}" \
      -n "${TRUSTYAI_OPERATOR_NAMESPACE}" \
      --replicas=0
  else
    echo "  WARNING: TrustyAI operator deployment not found; continuing without scale-down."
  fi
else
  echo "  Skipping TrustyAI operator scale-down (DISABLE_OPERATOR_SCALE_DOWN=true)."
fi

ORIGINAL_EVALHUB_IMAGE="$(
  oc get deployment evalhub -n "${NS}" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="evalhub")].image}' 2>/dev/null || true
)"

oc set image deployment/evalhub -n "${NS}" "evalhub=${EVALHUB_IMAGE}"

echo "  Patching sidecar image in evalhub-config..."
TMPFILE=$(mktemp)
oc get configmap evalhub-config -n "${NS}" -o jsonpath='{.data.config\.yaml}' > "${TMPFILE}"
if [[ ! -s "${TMPFILE}" ]]; then
  echo "ERROR: evalhub-config is empty or unreadable in namespace ${NS}."
  rm -f "${TMPFILE}"
  exit 1
fi
ORIGINAL_CONFIG_BACKUP=$(mktemp)
cp "${TMPFILE}" "${ORIGINAL_CONFIG_BACKUP}"

python3 - "${TMPFILE}" "${EVALHUB_IMAGE}" "${EVALHUB_INSECURE_SKIP_VERIFY}" <<'PY'
import sys
import yaml

path = sys.argv[1]
image = sys.argv[2]
insecure_skip_verify = sys.argv[3].strip().lower() == "true"

with open(path, encoding="utf-8") as handle:
    data = yaml.safe_load(handle.read()) or {}

if not isinstance(data, dict):
    raise SystemExit("evalhub-config config.yaml must be a YAML mapping at top-level")

sidecar = data.get("sidecar")
if not isinstance(sidecar, dict):
    sidecar = {}
    data["sidecar"] = sidecar

sidecar_container = sidecar.get("sidecar_container")
if not isinstance(sidecar_container, dict):
    sidecar_container = {}
    sidecar["sidecar_container"] = sidecar_container
sidecar_container["image"] = image

eval_hub = sidecar.get("eval_hub")
if not isinstance(eval_hub, dict):
    eval_hub = {}
    sidecar["eval_hub"] = eval_hub
eval_hub["insecure_skip_verify"] = insecure_skip_verify

# Keep compatibility with older evalhub config schema where service.eval_sidecar_image is consumed.
service = data.get("service")
if not isinstance(service, dict):
    service = {}
    data["service"] = service
service["eval_sidecar_image"] = image

with open(path, "w", encoding="utf-8") as handle:
    yaml.safe_dump(data, handle, sort_keys=False)
PY

oc create configmap evalhub-config -n "${NS}" \
  --from-file=config.yaml="${TMPFILE}" --dry-run=client -o yaml | oc apply -f -
rm -f "${TMPFILE}"

oc rollout restart deployment/evalhub -n "${NS}"
oc rollout status deployment/evalhub -n "${NS}" --timeout=120s

echo "=== Step 5: Create MLflow route (if needed) ==="
if ! oc get namespace "${MLFLOW_ROUTE_NAMESPACE}" > /dev/null 2>&1; then
  echo "  WARNING: Namespace ${MLFLOW_ROUTE_NAMESPACE} not accessible; skipping MLflow route setup."
elif [[ "$(oc auth can-i get routes -n "${MLFLOW_ROUTE_NAMESPACE}" 2>/dev/null || echo no)" != "yes" ]]; then
  echo "  WARNING: Missing permission to inspect routes in ${MLFLOW_ROUTE_NAMESPACE}; skipping MLflow route setup."
elif oc get route mlflow -n "${MLFLOW_ROUTE_NAMESPACE}" > /dev/null 2>&1; then
  echo "  MLflow route already exists."
elif [[ "$(oc auth can-i create routes -n "${MLFLOW_ROUTE_NAMESPACE}" 2>/dev/null || echo no)" == "yes" ]]; then
  oc create route passthrough mlflow --service=mlflow --port=8443 -n "${MLFLOW_ROUTE_NAMESPACE}"
  echo "  MLflow route created."
else
  echo "  WARNING: Missing permission to create MLflow route in ${MLFLOW_ROUTE_NAMESPACE}; skipping."
fi

echo "=== Step 6: Set up pull secret for adapter image ==="
if [[ "${SKIP_PULL_SECRET}" == "true" ]]; then
  echo "  Skipping pull secret setup (SKIP_PULL_SECRET=true)."
else
  AUTHFILE="/run/user/$(id -u)/containers/auth.json"
  if [[ ! -f "${AUTHFILE}" ]]; then
    AUTHFILE="${HOME}/.docker/config.json"
  fi
  if [[ -f "${AUTHFILE}" ]]; then
    oc create secret generic "${PULL_SECRET_NAME}" -n "${NS}" \
      --from-file=.dockerconfigjson="${AUTHFILE}" \
      --type=kubernetes.io/dockerconfigjson --dry-run=client -o yaml | oc apply -f -
    oc secrets link default "${PULL_SECRET_NAME}" --for=pull -n "${NS}"
    oc secrets link evalhub-${NS}-job "${PULL_SECRET_NAME}" --for=pull -n "${NS}" 2>/dev/null || true
    echo "  Pull secret configured (${PULL_SECRET_NAME})."
  else
    echo "  WARNING: No container auth file found. Adapter image must be public or pull secret must be created manually."
  fi
fi

ROUTE=$(oc get route evalhub -n "${NS}" -o jsonpath='{.spec.host}' 2>/dev/null || true)
MLFLOW_ROUTE_HOST=$(oc get route mlflow -n "${MLFLOW_ROUTE_NAMESPACE}" -o jsonpath='{.spec.host}' 2>/dev/null || true)
echo ""
echo "=== Done ==="
echo "  EvalHub: https://${ROUTE}"
echo "  Health:  curl -sf https://${ROUTE}/api/v1/health"
if [[ -n "${MLFLOW_ROUTE_HOST}" ]]; then
  echo "  MLflow:  https://${MLFLOW_ROUTE_HOST}/mlflow"
else
  echo "  MLflow:  route unavailable in ${MLFLOW_ROUTE_NAMESPACE}"
fi
