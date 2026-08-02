# RHOAI Cluster GPU and vLLM Serving Architecture

Recon notes for the `agen-e2e-rhoai2` OpenShift cluster used by CI integration tests
(`ci-testing` namespace). Captured during RHAIENG-6264 guardrails work (Aug 2026).

## Cluster overview

| Item | Value |
|------|-------|
| API server | `https://api.agen-e2e-rhoai2.p5ui.p3.openshiftapps.com:443` |
| OpenShift version | 4.20.13 (Kubernetes 1.33.6) |
| RHOAI DSC | `default-dsc` Ready |
| CI test namespace | `ci-testing` |
| LLM serving namespace | `llama-serving` |
| Region / zone | `us-east-2` / `us-east-2b` |

## GPU nodes

The cluster has **8 worker nodes** total. **2 are GPU workers** in the Hypershift node pool
`agen-e2e-rhoai2-gpu`. Both are AWS `g5.2xlarge` instances with a single NVIDIA A10G GPU
(Ampere, compute capability 8.6, ~23 GB VRAM).

| Node | Instance type | GPU | VRAM | Allocated | Notes |
|------|---------------|-----|------|-----------|-------|
| `ip-10-0-3-114` | `g5.2xlarge` | 1× NVIDIA A10G | ~23 GB | 0/1 | Free |
| `ip-10-0-3-176` | `g5.2xlarge` | 1× NVIDIA A10G | ~23 GB | 1/1 | Runs `vllm-qwen` |

The remaining 6 workers are CPU-only (`m5.2xlarge` and similar) with no `nvidia.com/gpu`
resource.

### Scheduling

- **Taint:** `nvidia.com/gpu=present:NoSchedule` on both GPU nodes.
- GPU workloads must request `nvidia.com/gpu` and tolerate the NVIDIA GPU taint.
- **CUDA:** driver 580.105.08, runtime 13.0; NVIDIA GPU Operator components are installed
  on GPU nodes.

**Cluster GPU summary:** 2 GPUs allocatable, 1 in use, 1 free.

## vLLM serving (`vllm-qwen`)

Direct GPU-backed LLM inference in `llama-serving`.

| Item | Value |
|------|-------|
| Deployment | `vllm-qwen` |
| Pod | `vllm-qwen-84fc465556-hzm2n` |
| Node | `ip-10-0-3-176` (GPU) |
| Service | `vllm-svc.llama-serving.svc.cluster.local:8000` |
| Image | `vllm/vllm-openai:latest` |
| GPU | `nvidia.com/gpu: 1` (request + limit) |
| Served model name | `qwen2-5-7b-instruct` |
| HuggingFace model | `Qwen/Qwen2.5-7B-Instruct` |
| Max model length | 32768 |
| Tool calling | `--enable-auto-tool-choice` |

### API

```text
GET  http://vllm-svc.llama-serving.svc.cluster.local:8000/v1/models
POST http://vllm-svc.llama-serving.svc.cluster.local:8000/v1/chat/completions
```

Verified reachable from `ci-testing` pods (e.g. via `oc exec` on a running agent deployment).

## OGX gateway (`ogx-serving`)

OGX is a **CPU-only API gateway** — it does not request a GPU. It runs on a standard
worker node and proxies or hosts models depending on provider type.

| Item | Value |
|------|-------|
| Deployment | `ogx-serving` |
| Pod | `ogx-serving-667b5b47c7-4wnmd` |
| Node | `ip-10-0-3-239` (`m5.2xlarge`, no GPU) |
| Service | `ogx-serving-service.llama-serving.svc.cluster.local:8321` |
| Image | `registry.redhat.io/rhoai/odh-ogx-core-rhel9` |
| Resources | 1 CPU, 1 Gi memory (no GPU) |
| Route | `ogx-serving-https-llama-serving.apps.rosa.agen-e2e-rhoai2.p5ui.p3.openshiftapps.com` |

### Providers (from `ogx-serving-config` ConfigMap)

| Provider | Type | Backend | Runs on |
|----------|------|---------|---------|
| `vllm` | `remote::vllm` | `http://vllm-svc.llama-serving.svc.cluster.local:8000/v1` | GPU (vLLM pod) |
| `sentence-transformers` | `inline::sentence-transformers` | In-process in OGX pod | CPU (OGX pod) |
| `pgvector` | `remote::pgvector` | `postgres.adonheis-testing.svc.cluster.local:5432` | External Postgres |

`refresh_models: true` on the vLLM provider causes OGX to discover models from vLLM and
expose them under the `vllm/` prefix.

### Models exposed via OGX

```text
GET http://ogx-serving-service.llama-serving.svc.cluster.local:8321/v1/models
```

| Model ID | Source | Type |
|----------|--------|------|
| `vllm/qwen2-5-7b-instruct` | Proxied from vLLM | LLM |
| `sentence-transformers/all-MiniLM-L6-v2` | Inline in OGX | Embedding |
| `sentence-transformers/nomic-ai/nomic-embed-text-v1.5` | Inline in OGX | Embedding |

## Architecture

```text
                    ┌─────────────────────────────────────────┐
                    │  ci-testing (agents, integration tests) │
                    └───────────────┬─────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │ vllm-svc:8000    │  │ ogx-serving:8321 │  │ NemoGuardrails   │
   │ (direct path)    │  │ (gateway path)   │  │ (planned)        │
   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
            │                     │                     │
            │              ┌──────┴──────┐              │
            │              │  OGX pod    │              │
            │              │  (CPU only) │              │
            │              └──────┬──────┘              │
            │                     │ remote::vllm        │
            ▼                     ▼                     ▼
   ┌─────────────────────────────────────────┐   ┌─────────────┐
   │ vllm-qwen pod (GPU node, A10G)          │◄──│ guardrails  │
   │ Qwen2.5-7B-Instruct                     │   │ → LLM       │
   └─────────────────────────────────────────┘   └─────────────┘
```

**QG4 CI convention today** (direct vLLM, no OGX hop):

```text
BASE_URL=http://vllm-svc.llama-serving.svc.cluster.local:8000/v1
MODEL_ID=qwen2-5-7b-instruct
API_KEY=not-needed
```

## Network access

- `llama-serving` has a `allow-from-all-namespaces` NetworkPolicy — pods in `ci-testing`
  can reach both `vllm-svc` and `ogx-serving-service` without extra policy.
- No `InferenceService` or `LLMInferenceService` CRs are deployed; LLM serving is raw
  Deployments, not KServe-managed.

## Implications for guardrails (RHAIENG-6264)

### NeMo Guardrails CR

The `NemoGuardrails` CR (TrustyAI operator) is **CPU-only** for the self-check `local`/`rhoai`
profile. It does not need a GPU unless you add GPU-backed safety classifiers.

### LLM backend for `guardrails/config/rhoai/`

Two valid `base_url` choices for the guardrails ConfigMap:

| Path | `base_url` | `model` |
|------|------------|---------|
| **Direct vLLM** (recommended) | `http://vllm-svc.llama-serving.svc.cluster.local:8000/v1` | `qwen2-5-7b-instruct` |
| **Via OGX** | `http://ogx-serving-service.llama-serving.svc.cluster.local:8321/v1` | `vllm/qwen2-5-7b-instruct` |

Direct vLLM matches existing QG4 CI vars and adds fewer moving parts. OGX is useful when
testing the unified RHOAI model-discovery path.

### Agent wiring

```text
Agent BASE_URL  →  NemoGuardrails Service (port 80)   # NOT vLLM directly
Guardrails LLM  →  vllm-svc (or OGX)                 # backend inside config.yaml
```

### Free GPU capacity

One A10G (`ip-10-0-3-114`) is idle. Available for additional workloads such as a second
LLM, Nemotron safety classifiers, or other GPU experiments — not required for the basic
self-check guardrails profile.

## Related repo references

- Guardrailed agent: `agents/langgraph/examples/guardrailed_agent/`
- QG4 integration workflow: `.github/workflows/agent-deployment-test.yaml`
- Shared integration harness: `tests/integration/conftest.py` (requires `ci-testing` namespace)
- LLMInferenceService template (not deployed on this cluster): `infrastructure/llm-d/llminferenceservice.yaml`
