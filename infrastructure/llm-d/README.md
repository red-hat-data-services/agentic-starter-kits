# llm-d Infrastructure

Deploy llm-d on OpenShift AI for intelligent LLM inference routing across multiple vLLM replicas.

llm-d is a Kubernetes-native routing and orchestration layer that sits in front of vLLM instances, providing prefix-cache-aware routing, queue-based load balancing, and active-request scoring instead of naive round-robin. As of RHOAI 3.6, these manifests also cover batch inference via the llm-d batch gateway.

## Contents

| File | Description |
|------|-------------|
| [`llminferenceservice.yaml`](llminferenceservice.yaml) | LLMInferenceService template (v1alpha2 with `baseRefs` presets) |
| [`maas-gateway.yaml`](maas-gateway.yaml) | The `maas-default-gateway` Gateway (required before MaaS reconciles; no-op if it already exists) |
| [`network-policies.yaml`](network-policies.yaml) | Required NetworkPolicies (RHOAI defaults block port 8000) |
| [`batch-deps.yaml`](batch-deps.yaml) | Dev-grade Redis + PostgreSQL backing services for the batch gateway |
| [`batch-internal-gateway.yaml`](batch-internal-gateway.yaml) | Cluster-internal Gateway for batch processor → model traffic |
| [`batch-llm-route.yaml`](batch-llm-route.yaml) | HTTPRoute from the internal gateway to the InferencePool (bare + prefixed paths) |
| [`llmbatchgateway.yaml`](llmbatchgateway.yaml) | PVC, credentials Secret, and LLMBatchGateway custom resource |
| [`test_distribution.py`](test_distribution.py) | Traffic distribution and performance test script |

## Quick Start

See the full deployment guide: [docs/llm-d-deployment.md](../../docs/llm-d-deployment.md)

## Test Script Usage

```bash
uv run --with aiohttp python test_distribution.py \
  --url https://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1 \
  --model <MODEL_NAME>
```
