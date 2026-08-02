# Deploying Guardrailed Agent on RHOAI (ci-testing)

This directory deploys the **nemoguard** NeMo Guardrails profile to OpenShift via the
`NemoGuardrails` CRD (TrustyAI operator), then wires the agent's `BASE_URL` to that
in-cluster guardrails Service — not directly to vLLM.

## Architecture

```text
Agent (Helm)  →  NemoGuardrails Service :80/v1  →  vLLM + NVIDIA NIM classifiers
```

The ConfigMap is a **single monolithic map** per RHOAI constraints (config.yaml,
prompts.yml, rails.co, actions.py, topic_policy.co) sourced from
`guardrails/config/nemoguard/`.

## Prerequisites

- `oc` logged into the target cluster; namespace `ci-testing` for integration tests
- TrustyAI operator with `NemoGuardrails` CRD installed
- In-cluster LLM at `vllm-svc.llama-serving.svc.cluster.local:8000` (default)
- **NVIDIA NIM API key** for nemoguard safety classifiers

## Quick start

```bash
cd agents/langgraph/examples/guardrailed_agent

# 1. Cluster env (nemoguard profile values)
cp deploy/overlays/ci-testing/cluster.env.example deploy/overlays/ci-testing/cluster.env
# Edit cluster.env — set NVIDIA_API_KEY

# 2. Agent .env (BASE_URL must point at guardrails, not vLLM)
cp .env.example .env
# BASE_URL=http://langgraph-guardrailed-agent-guardrails.ci-testing.svc.cluster.local/v1
# MODEL_ID=qwen2-5-7b-instruct
# CONTAINER_IMAGE=image-registry.openshift-image-registry.svc:5000/ci-testing/langgraph-guardrailed-agent:latest

# 3. Deploy guardrails + agent
make deploy-guardrails
make build-openshift   # or set CONTAINER_IMAGE
make deploy-rhoai
```

## Inject NIM API key (Secret only)

If guardrails manifests are already applied and you only need to rotate the key:

```bash
# From cluster.env
make deploy-guardrails-secrets

# Or one-shot (replace with your key)
oc create secret generic langgraph-guardrailed-agent-guardrails-secrets \
  --namespace=ci-testing \
  --from-literal=api-key=not-needed \
  --from-literal=nvidia-api-key="$NVIDIA_API_KEY" \
  --dry-run=client -o yaml | oc apply -f -
```

Restart the guardrails pod after secret updates:

```bash
oc rollout restart deployment/langgraph-guardrailed-agent-guardrails -n ci-testing
```

## Verify

```bash
# Guardrails config (nemoguard profile)
oc exec -n ci-testing deploy/langgraph-guardrailed-agent -- \
  curl -s http://langgraph-guardrailed-agent-guardrails.ci-testing.svc.cluster.local/v1/rails/configs

# Agent health (guardrails_reachable must be true)
ROUTE=$(oc -n ci-testing get route langgraph-guardrailed-agent -o jsonpath='{.spec.host}')
curl -s "https://${ROUTE}/health" | jq .
```

## Makefile targets

| Target | Description |
|--------|-------------|
| `make render-guardrails-configmap` | Generate `deploy/manifests/02-guardrails-configmap.yaml` |
| `make deploy-guardrails-secrets` | Apply Secret from `cluster.env` |
| `make deploy-guardrails` | Render ConfigMap + apply Kustomize overlay |
| `make undeploy-guardrails` | Delete CR, ConfigMap, Secret |
| `make deploy-rhoai` | `deploy-guardrails` then `make deploy` |
| `make undeploy-rhoai` | `undeploy` + `undeploy-guardrails` |
| `make deploy-rhoai-dry-run` | `oc kustomize` preview |

## Integration tests

```bash
export NVIDIA_API_KEY=nvapi-...
export MODEL_ID=qwen2-5-7b-instruct
export BASE_URL=http://langgraph-guardrailed-agent-guardrails.ci-testing.svc.cluster.local/v1
export API_KEY=not-needed

make test-integration
```

`tests/integration/test_guardrails_cluster.py` exercises rail behavior when
`GUARDRAILS_INTEGRATION_URL` is set (guardrails Route URL, or in-cluster Service URL
from a pod).

## Customization

Edit `deploy/overlays/ci-testing/cluster.env` to change:

- `LLM_BASE_URL` / `MODEL_ID` — main LLM backend (vLLM or OGX)
- `CONTENT_SAFETY_*` / `TOPIC_CONTROL_*` — NIM classifier models
- `NVIDIA_API_KEY` — NIM classifier API key (Secret `nvidia-api-key` → pod env `NVIDIA_API_KEY`)

Re-run `make deploy-guardrails` after changes to regenerate the ConfigMap and roll out.
