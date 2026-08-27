# Deploying Guardrailed Agent on RHOAI

This directory deploys the **nemoguard** NeMo Guardrails profile to OpenShift AI via the
`NemoGuardrails` CRD (TrustyAI operator), then wires the agent's `BASE_URL` to that
in-cluster guardrails Service — not directly to vLLM.

Apply with `make deploy-guardrails` (or `make deploy-rhoai`). Do **not**
`oc apply -k` these manifests — the CR contains `${OTEL_*}` placeholders that
only the Makefile substitutes. The overlay directory `overlays/ci-testing/`
holds cluster env values (QG4 name); it is not the deploy namespace.

## Architecture

```text
Agent (Helm)  →  NemoGuardrails Service :80/v1  →  vLLM + NVIDIA NIM classifiers
```

The ConfigMap is a **single monolithic map** per RHOAI constraints (config.yaml,
prompts.yml, rails.co, actions.py, topic_policy.co) sourced from
`guardrails/config/nemoguard/`.

## Prerequisites

- `oc` logged into the target cluster. Guardrails and the Helm agent both deploy
  into the current project (`oc project -q`), overridable via `GUARDRAILS_NAMESPACE`
- `envsubst` (GNU gettext). On macOS: `brew install gettext` and add
  `$(brew --prefix gettext)/bin` to `PATH` (keg-only)
- TrustyAI operator with `NemoGuardrails` CRD installed
- In-cluster LLM at `vllm-svc.llama-serving.svc.cluster.local:8000` (default)
- **NVIDIA NIM API key** for nemoguard safety classifiers

## Quick start

```bash
cd agents/langgraph/examples/guardrailed_agent
NS=$(oc project -q)

# 1. Cluster env (nemoguard profile values)
cp deploy/overlays/ci-testing/cluster.env.example deploy/overlays/ci-testing/cluster.env
# Edit cluster.env — set NVIDIA_API_KEY

# 2. Agent .env (BASE_URL must point at guardrails, not vLLM)
cp .env.example .env
# BASE_URL=http://langgraph-guardrailed-agent-guardrails.${NS}.svc.cluster.local/v1
# MODEL_ID=qwen2-5-7b-instruct
# CONTAINER_IMAGE=image-registry.openshift-image-registry.svc:5000/${NS}/langgraph-guardrailed-agent:latest

# 3. Build + deploy guardrails + agent
# Optional tracing: see deploy/tracing/README.md, then uncomment the whole
# GUARDRAILS_TRACING_ENABLED=true block in cluster.env (endpoint required)
make build-openshift   # or set CONTAINER_IMAGE
make deploy-rhoai      # fails if BASE_URL does not match the current oc project
```

## Inject NIM API key (Secret only)

If guardrails manifests are already applied and you only need to rotate the key:

```bash
# From cluster.env
make deploy-guardrails-secrets

# Or one-shot (replace with your key)
NS=$(oc project -q)
oc create secret generic langgraph-guardrailed-agent-guardrails-secrets \
  --namespace="$NS" \
  --from-literal=api-key=not-needed \
  --from-literal=nvidia-api-key="$NVIDIA_API_KEY" \
  --dry-run=client -o yaml | oc apply -f -
```

Restart the guardrails pod after secret updates:

```bash
NS=$(oc project -q)
oc rollout restart deployment/langgraph-guardrailed-agent-guardrails -n "$NS"
```

## Verify

```bash
NS=$(oc project -q)

# Guardrails config (nemoguard profile)
oc exec -n "$NS" deploy/langgraph-guardrailed-agent -- \
  curl -s "http://langgraph-guardrailed-agent-guardrails.${NS}.svc.cluster.local/v1/rails/configs"

# Agent health (guardrails_reachable must be true)
ROUTE=$(oc -n "$NS" get route langgraph-guardrailed-agent -o jsonpath='{.spec.host}')
curl -s "https://${ROUTE}/health" | jq .
```

## Makefile targets

| Target | Description |
|--------|-------------|
| `make render-guardrails-configmap` | Generate `deploy/manifests/02-guardrails-configmap.yaml` |
| `make deploy-guardrails-secrets` | Apply Secret from `cluster.env` |
| `make deploy-guardrails` | Render ConfigMap + apply CR/ConfigMap/Secret into `GUARDRAILS_NAMESPACE` |
| `make undeploy-guardrails` | Delete CR, ConfigMap, Secret from `GUARDRAILS_NAMESPACE` |
| `make deploy-rhoai` | `deploy-guardrails` then `make deploy` (requires matching `BASE_URL`) |
| `make undeploy-rhoai` | `undeploy` + `undeploy-guardrails` |
| `make deploy-rhoai-dry-run` | Preview substituted CR + ConfigMap for `GUARDRAILS_NAMESPACE` |

## Integration tests

QG4 runs these in project `ci-testing`. Elsewhere, set `BASE_URL` to the current
project's guardrails Service before `make test-integration`.

```bash
NS=$(oc project -q)
export NVIDIA_API_KEY=nvapi-...
export MODEL_ID=qwen2-5-7b-instruct
export BASE_URL=http://langgraph-guardrailed-agent-guardrails.${NS}.svc.cluster.local/v1
export API_KEY=not-needed

make test-integration
```

`tests/integration/test_guardrails_cluster.py` exercises rail behavior against the
guardrails Route when it exists. `GUARDRAILS_INTEGRATION_URL` is optional and only
needed to override auto-discovery. The in-cluster Service fallback is only usable
from a pod or another process already running inside the cluster network.

## Customization

Edit `deploy/overlays/ci-testing/cluster.env` to change:

- `LLM_BASE_URL` / `MODEL_ID` — main LLM backend (vLLM or OGX)
- `CONTENT_SAFETY_*` / `TOPIC_CONTROL_*` — NIM classifier models
- `NVIDIA_API_KEY` — NIM classifier API key (Secret `nvidia-api-key` → pod env `NVIDIA_API_KEY`)

Re-run `make deploy-guardrails` after changes to regenerate the ConfigMap and roll out.
