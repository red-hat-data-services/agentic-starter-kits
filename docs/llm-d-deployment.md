# Deploying llm-d on OpenShift AI

Deploy multiple vLLM instances across separate GPU nodes with llm-d orchestrating intelligent request routing (prefix-cache-aware, queue-based, active-request scoring). Optionally integrate with Llama Stack for the Responses API.

## Architecture

```text
Client → Llama Stack (optional) → Gateway → llm-d scheduler → vLLM pods (N x GPU nodes)
```

llm-d is a **routing and orchestration layer**, not a model-sharding tool. Each vLLM instance holds a complete copy of the model. llm-d intelligently routes requests across replicas to maximize KV cache hits and balance load.

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| **OpenShift cluster** | 4.19+ with ROSA HCP or self-managed |
| **RHOAI 3.4+** | Red Hat OpenShift AI operator (fast-3.x channel) |
| **NFD Operator** | Node Feature Discovery — detects GPU hardware. Create a `NodeFeatureDiscovery` instance after installing. |
| **NVIDIA GPU Operator** | Installs drivers and device plugins. Create a `ClusterPolicy` after installing. |
| **Red Hat Connectivity Link** | Provides Kuadrant/Authorino for auth — required by RHOAI 3.4 MaaS. Install from OperatorHub. |
| **Authorino TLS configured** | Authorino must have TLS enabled with a valid certificate. See [RHOAI documentation](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4). |
| **PostgreSQL database** | MaaS controller requires a `maas-db-config` secret in `redhat-ods-applications` with a `DB_CONNECTION_URL` key pointing to a PostgreSQL instance. See [RHOAI documentation](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4). |
| **User Workload Monitoring** | Must be enabled on the cluster for MaaS metrics. See [OpenShift monitoring documentation](https://docs.openshift.com/container-platform/latest/observability/monitoring/enabling-monitoring-for-user-defined-projects.html). |
| **Models-as-a-Service enabled** | Must be enabled in the DataScienceCluster (see below) |
| **Red Hat registry pull secret** | Access to `registry.redhat.io` for vLLM images |

> **Note:** The MaaS controller will fail to start if Authorino TLS, the PostgreSQL
> database secret, or User Workload Monitoring are not configured. Check the
> `maas-controller` pod logs for specific error messages if provisioning fails.

### Enable Models-as-a-Service

```bash
oc patch dsc default-dsc --type merge \
  -p '{"spec":{"components":{"kserve":{"modelsAsService":{"managementState":"Managed"}}}}}'
```

## Configuration Reference

The following values are specific to your environment. Replace all `<PLACEHOLDER>` values in the commands and YAML files below with your own.

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `<CLUSTER_NAME>` | Your ROSA cluster name | `my-cluster` |
| `<REGION>` | AWS region where the cluster runs | `us-east-2` |
| `<MODEL_URI>` | HuggingFace model URI (must fit on a single GPU) | `hf://openai/gpt-oss-20b` |
| `<MODEL_NAME>` | Model identifier used in API requests | `openai/gpt-oss-20b` |
| `<REPLICAS>` | Number of vLLM replicas (one per GPU node) | `6` |
| `<INSTANCE_TYPE>` | GPU instance type for the node pool | `g6.xlarge` (1x L4 23GB) |
| `<NODE_POOL_NAME>` | Label for GPU node pool scheduling | `gpu-llmd-nodes` |
| `<PULL_SECRET_FILE>` | Path to your Red Hat registry pull secret YAML | `my-pull-secret.yaml` |
| `<PULL_SECRET_NAME>` | Name of the pull secret in the cluster | `my-pull-secret` |
| `<VLLM_IMAGE>` | vLLM container image — get the latest digest from the [Red Hat Ecosystem Catalog](https://catalog.redhat.com/en/software/containers/rhaiis/vllm-cuda-rhel9) | `registry.redhat.io/rhaiis/vllm-cuda-rhel9@sha256:...` |
| `<GATEWAY_HOST>` | The maas-default-gateway external hostname (auto-assigned ELB or manually configured) | `a1b2c3.us-east-2.elb.amazonaws.com` |
| `<LLAMASTACK_ROUTE>` | Llama Stack external route hostname (if using Llama Stack) | `llamastack-route-redhat-ods-applications.apps.example.com` |

## Recommended Models

Choose a model that fits entirely on a single GPU — llm-d does not shard models across GPUs. Each replica loads the full model.

| Model | Size | Min GPU VRAM | Notes |
|-------|------|-------------|-------|
| `openai/gpt-oss-20b` | ~20B params | ~16 GB (quantized) | Tested with this guide on L4 (23GB) nodes |
| `meta-llama/Llama-3.1-8B-Instruct` | 8B params | ~8 GB (FP8) | Smaller model, works on most GPU types |

Set `<MODEL_URI>` to `hf://<model_name>` (e.g., `hf://openai/gpt-oss-20b`) and `<MODEL_NAME>` to the model identifier used in API requests (e.g., `openai/gpt-oss-20b`).

## Step 1: Create GPU Node Pool

Create a machine pool with GPU nodes. Each node should have at least one GPU with enough VRAM to hold your model.

```bash
rosa create machinepool --cluster <CLUSTER_NAME> \
  --name <NODE_POOL_NAME> \
  --instance-type <INSTANCE_TYPE> \
  --replicas <REPLICAS> \
  --labels "node-pool=<NODE_POOL_NAME>" \
  --region <REGION>
```

Wait for all nodes to be ready and GPUs detected:

```bash
oc get nodes -l node-pool=<NODE_POOL_NAME> \
  -o custom-columns='NAME:.metadata.name,GPU:.status.capacity.nvidia\.com/gpu,GPU_PRODUCT:.metadata.labels.nvidia\.com/gpu\.product'
```

## Step 2: Apply Pull Secret

Apply your Red Hat registry pull secret and link it to the default service account:

```bash
oc apply -f <PULL_SECRET_FILE> -n redhat-ods-applications
oc secrets link default <PULL_SECRET_NAME> --for=pull -n redhat-ods-applications
```

## Step 3: Deploy LLMInferenceService

Deploy the LLMInferenceService in the `redhat-ods-applications` namespace. This is required because the `data-science-gateway` only allows routes from this namespace.

A ready-to-use YAML template is at [`infrastructure/llm-d/llminferenceservice.yaml`](../infrastructure/llm-d/llminferenceservice.yaml). Edit the placeholders and apply:

```bash
oc apply -f infrastructure/llm-d/llminferenceservice.yaml
```

**Important:** `spec.router.scheduler: {}` must be explicitly set. Without it, the controller skips scheduler/router creation and you get vLLM pods but no intelligent routing.

**Gateway choice:** The YAML uses `maas-default-gateway` instead of `data-science-gateway`. The `data-science-gateway` has an OAuth proxy designed for browser access, which blocks programmatic API calls. The `maas-default-gateway` has no OAuth proxy and is suitable for API clients like Llama Stack.

## Step 4: Create Network Policies

The default RHOAI network policy blocks port 8000. Apply the required network policies:

```bash
oc apply -f infrastructure/llm-d/network-policies.yaml
```

See [`infrastructure/llm-d/network-policies.yaml`](../infrastructure/llm-d/network-policies.yaml) for details.

## Step 5: Configure Llama Stack (Optional)

If integrating with Llama Stack, set these environment variables in your Llama Stack deployment:

| Variable | Value | Notes |
|----------|-------|-------|
| `VLLM_URL` | `http://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1` | Must end with `/v1` — the OpenAI SDK appends `/models`, `/chat/completions`, etc. to this base URL |
| `VLLM_TLS_VERIFY` | `false` | Required when using self-signed certs |
| `VLLM_API_KEY` | *(leave empty)* | Not needed — the maas-default-gateway has no auth |

To find your `<GATEWAY_HOST>`:

```bash
oc get llminferenceservice <SERVICE_NAME> -n redhat-ods-applications -o jsonpath='{.status.url}'
```

If deploying Llama Stack in the same namespace with an external route, apply the Llama Stack network policy from `network-policies.yaml` to allow ingress from the OpenShift router.

## Verification

### Check deployment status

```bash
# LLMInferenceService should show Ready: True
oc get llminferenceservice -n redhat-ods-applications

# Expected: N vLLM pods (1/1 Running) + 1 router-scheduler pod (2/2 Running)
oc get pods -n redhat-ods-applications | grep <SERVICE_NAME>

# InferencePool should exist
oc get inferencepool -n redhat-ods-applications
```

### Test inference

```bash
# Direct to llm-d gateway
curl -s http://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'

# Through Llama Stack (if configured)
curl -s https://<LLAMASTACK_ROUTE>/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","input":"Who is the president of the United States?"}'
```

### Test traffic distribution

Use the included test script to validate llm-d's intelligent routing:

```bash
uv run --with aiohttp python infrastructure/llm-d/test_distribution.py \
  --url http://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1 \
  --model <MODEL_NAME>
```

See [`infrastructure/llm-d/test_distribution.py`](../infrastructure/llm-d/test_distribution.py) for details.

## Key Notes

- **llm-d is a routing/orchestration layer.** Each vLLM instance holds a complete copy of the model. llm-d routes requests intelligently (prefix-cache-aware, queue-based, active-request scoring) rather than round-robin.
- **LLMInferenceService** is the RHOAI-native way to deploy llm-d. It manages vLLM pods, the scheduler, InferencePool, and HTTPRoute automatically.
- **RHOAI 3.4+ MaaS** requires Red Hat Connectivity Link (Kuadrant/Authorino) for auth and rate limiting.
- **Use `maas-default-gateway`** for programmatic/API access. The `data-science-gateway` has an OAuth proxy meant for browser access.
- **Custom NetworkPolicies are required.** The default RHOAI network policy blocks port 8000, which vLLM uses for serving.
- **Choose a model that fits on a single GPU.** llm-d does not shard models across GPUs — each replica needs the full model in VRAM.
