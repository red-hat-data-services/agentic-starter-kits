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
Agent (Helm)  →  NemoGuardrails Service :80/v1  →  vLLM (main LLM + topic-control classifier)
                                             ↘  NVIDIA NIM (content-safety classifier)
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
- **Topic-control classifier** deployed via `make deploy-model` (see the next
  section) — NVIDIA removed the hosted NIM function for
  `nvidia/nemotron-3.5-content-safety` (RHAIENG-8048), so it runs in-cluster
- **NVIDIA NIM API key** for the content-safety classifier

## Topic-control classifier (self-hosted vLLM)

The nemoguard profile's topic-control rail uses `nvidia/nemotron-3.5-content-safety`.
NVIDIA removed the hosted NIM function for that model (every topic-policy call
404'd; surfaced by the guardrails proxy as "Internal server error" — RHAIENG-8048),
so the classifier is served in-cluster by the manifests in `deploy/model-serving/`.

```bash
# Base — bf16-capable GPUs (A10G and newer; the CI cluster layout)
make deploy-model                                    # into llama-serving (MODEL_SERVING_NAMESPACE)

# T4 / sm75 overlay — the config validated on the dev cluster (fp16 + attention
# backend overrides; see overlays/t4/kustomization.yaml comments)
make deploy-model-t4

# Teardown (keeps the PVC with the ~8.6 GB of weights for fast redeploys)
make undeploy-model
```

First boot downloads the weights into PVC `nemotron-model-storage` (~8.6 GB,
several minutes); readiness gates on vLLM's `/health`. To pre-warm the PVC on a
busy cluster, run the same download once from any CPU pod — the Deployment's
init container skips the download when `/mnt/models/config.json` exists.

**Prerequisites on the target cluster:**

- A free GPU the pod can claim. On clusters where all GPUs are occupied, the
  pod stays `Pending` on `Insufficient nvidia.com/gpu`. On the e2e CI cluster
  the GPU machine pool autoscales (min=1/max=2) and brought up a second
  g5.2xlarge by itself for the pending pod (it carries the taint toleration);
  clusters without autoscaling need the node added manually. Note the A10G
  (24 GB) cannot host both this classifier (~10–12 GB) and the 7B main model
  (~15 GB weights, 0.9 default memory util) on one card.
- `cluster-admin` (or a pre-granted `anyuid`) for the init container's
  `runAsUser: 0` weight download — `make deploy-model` attempts the SCC grant.
- A Docker Hub pull secret on clusters whose global pull secret lacks it (the
  vLLM image is `vllm/vllm-openai`). `make deploy-model` best-effort links
  `$(MODEL_SERVING_PULL_SECRET)` (default `dockerhub`) to the `nemotron-vllm`
  SA; override or pre-link with
  `oc -n <ns> secrets link nemotron-vllm <secret> --for=pull`.

The Service is
`nemotron-3-5-content-safety-svc.llama-serving.svc.cluster.local:8080/v1` —
that URL is baked into `cluster.env.example` as `TOPIC_CONTROL_LLM_BASE_URL`.

Two invariants a unit test enforces (`tests/test_deploy_manifests.py`):

- `--served-model-name` must equal `TOPIC_CONTROL_MODEL_ID` exactly (vLLM 404s
  unknown names; the proxy always sends that id)
- the id must keep containing `nemotron-3.5-content-safety` — custom-policy
  mode in `guardrails/generate_config.py` keys off a substring match of it

**Ordering for CI clusters**: deploy the classifier *before* merging/applying a
`cluster.env` that sets `TOPIC_CONTROL_MODEL_ENGINE=openai`. Once the config
switches, every topic-policy rail call depends on that Service answering.
Rollback is config-first too: restore `TOPIC_CONTROL_MODEL_ENGINE=nim` (or
point `TOPIC_CONTROL_LLM_BASE_URL` elsewhere) and re-run `make deploy-guardrails`.

## Quick start

```bash
cd agents/langgraph/examples/guardrailed_agent
NS=$(oc project -q)

# 0. Topic-control classifier (once per cluster — see section above)
make deploy-model       # or deploy-model-t4 on T4-class GPUs

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
| `make deploy-model` | Deploy topic-control classifier (vLLM) into `MODEL_SERVING_NAMESPACE` (bf16 GPU) |
| `make deploy-model-t4` | Same, T4/sm75 overlay (fp16 + attention/sampler overrides) |
| `make undeploy-model` | Delete classifier Deployment/Service/SA (keeps the weights PVC) |

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
- `CONTENT_SAFETY_*` — NIM classifier model (still NVIDIA-hosted)
- `TOPIC_CONTROL_*` — topic-control classifier: `MODEL_ENGINE=openai` +
  `LLM_BASE_URL` pointing at `nemotron-3-5-content-safety-svc` (keep
  `MODEL_ID` exactly as shipped — see the classifier section above)
- `NVIDIA_API_KEY` — content-safety NIM key (Secret `nvidia-api-key` → pod env `NVIDIA_API_KEY`)

Re-run `make deploy-guardrails` after changes to regenerate the ConfigMap and roll out.
