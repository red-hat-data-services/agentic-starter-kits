# llm-d Infrastructure

Deploy llm-d on OpenShift AI for intelligent LLM inference routing across multiple vLLM replicas.

llm-d is a Kubernetes-native routing and orchestration layer that sits in front of vLLM instances, providing prefix-cache-aware routing, queue-based load balancing, and active-request scoring instead of naive round-robin.

## Contents

| File | Description |
|------|-------------|
| [`llminferenceservice.yaml`](llminferenceservice.yaml) | LLMInferenceService custom resource template |
| [`network-policies.yaml`](network-policies.yaml) | Required NetworkPolicies (RHOAI defaults block port 8000) |
| [`test_distribution.py`](test_distribution.py) | Traffic distribution and performance test script |

## Quick Start

See the full deployment guide: [docs/llm-d-deployment.md](../../docs/llm-d-deployment.md)

## Test Script Usage

```bash
uv run --with aiohttp python test_distribution.py \
  --url http://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1 \
  --model <MODEL_NAME>
```
