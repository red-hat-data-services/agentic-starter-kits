# Deploying llm-d on OpenShift AI

Deploy multiple vLLM instances across separate GPU nodes with llm-d orchestrating intelligent request routing (prefix-cache-aware, queue-based, active-request scoring). As of RHOAI 3.6, llm-d deployments additionally serve the Anthropic-compatible Messages API, support OpenAI-compatible batch inference, and expose multi-tenant model paths.

Everything in this guide was verified on RHOAI 3.6.0 (OpenShift 4.22, ROSA).

## Architecture

```text
Online:   Client → Gateway (maas-default-gateway) → llm-d scheduler → vLLM pods (N x GPU nodes)
Batch:    Client → Gateway → batch apiserver (/v1/batches, /v1/files) → Redis/PostgreSQL
          → async processor → internal gateway → llm-d scheduler → vLLM pods
```

llm-d is a **routing and orchestration layer**, not a model-sharding tool. Each vLLM instance holds a complete copy of the model. llm-d intelligently routes requests across replicas to maximize KV cache hits and balance load.

## What's new in RHOAI 3.6

| Capability | Details |
|------------|---------|
| **v1alpha2 CRD + presets** | `LLMInferenceService` uses `baseRefs` to reference versioned `LLMInferenceServiceConfig` presets that supply the vLLM launch command, probes, and security context. No more hand-written liveness probes or launch scripts. |
| **Messages API** | The gateway routes `/v1/messages` — vLLM's Anthropic-compatible API — alongside the OpenAI-compatible endpoints. Works with Anthropic SDK clients. |
| **Batch inference (GA)** | The llm-d batch gateway provides OpenAI-compatible `/v1/batches` and `/v1/files` for asynchronous, fire-and-forget workloads, enabled via the `aigateway` DSC component. |
| **Tool-calling model validation** | Red Hat validates tool-calling models (e.g., GLM, Kimi, Inkling-Small families via BFCL v4). Serving a tool-calling model requires the right vLLM `--tool-call-parser` — see [tool calling](#tool-calling). |
| **MaaS multi-tenancy** | Models are additionally served under tenant-scoped paths: `/publishers/<namespace>/models/<model>/v1/...`. MaaS configuration moved from `kserve.modelsAsService` to the `aigateway.modelsAsService` DSC component. |
| **GatewayConfig CRD** | Gateways are managed declaratively via the `GatewayConfig` custom resource (`services.platform.opendatahub.io/v1alpha1`). |

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| **OpenShift cluster** | 4.19+ with ROSA HCP or self-managed (verified on 4.22) |
| **RHOAI 3.6+** | Red Hat OpenShift AI operator (fast-3.x channel) |
| **NFD Operator** | Node Feature Discovery — detects GPU hardware. Create a `NodeFeatureDiscovery` instance after installing. |
| **NVIDIA GPU Operator** | Installs drivers and device plugins. Create a `ClusterPolicy` after installing. Note: it taints GPU nodes with `nvidia.com/gpu=true:NoSchedule` — your workload needs a matching toleration (included in the template). |
| **AI Gateway component** | MaaS gateway and (optionally) batch gateway, enabled in the DataScienceCluster (see below) |
| **Red Hat Connectivity Link** | *Optional* — provides Kuadrant/Authorino auth. Without it, gateway auth is disabled via the `security.opendatahub.io/enable-auth: 'false'` annotation (as in this guide). **Warning:** in that configuration, any client that can reach the gateway host can invoke the model and consume GPU capacity — fine for isolated development clusters only. Install Connectivity Link and drop the annotation for production. |
| **Red Hat registry pull secret** | Access to `registry.redhat.io` for vLLM images |

### Enable the AI Gateway component

In RHOAI 3.6, Models-as-a-Service and the batch gateway live under the
`aigateway` DSC component (they moved from `kserve` in 3.4). The parent
component must be `Managed` for its submodules to activate:

```bash
# MaaS gateway (required for the maas-default-gateway used in this guide)
oc patch dsc default-dsc --type merge \
  -p '{"spec":{"components":{"aigateway":{"managementState":"Managed","modelsAsAService":{"managementState":"Managed"}}}}}'

# Batch gateway (optional — see "Batch inference" below)
oc patch dsc default-dsc --type merge \
  -p '{"spec":{"components":{"aigateway":{"batchGateway":{"managementState":"Managed"}}}}}'
```

> **Note:** enabling only `batchGateway` while `aigateway.managementState` is
> `Removed` has no effect — submodules require the parent module to be
> `Managed`.

### Create the MaaS gateway

The `maas-default-gateway` Gateway **must already exist** before the MaaS
controller can reconcile — the component does not create it. On clusters where
a model was deployed through the OpenShift AI dashboard, the gateway already
exists and this step is a no-op. On CLI-only clusters, create it:

```bash
oc apply -f infrastructure/llm-d/maas-gateway.yaml
```

See [`infrastructure/llm-d/maas-gateway.yaml`](../infrastructure/llm-d/maas-gateway.yaml).
Without it, `maas-controller` logs repeat
`gateway openshift-ingress/maas-default-gateway not found: the specified
Gateway must exist before enabling MaaS platform reconcile` and any
`LLMInferenceService` referencing the gateway stays unready.

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
| `<VLLM_IMAGE>` | vLLM container image — see the [vLLM image note](#vllm-image-requirements) below | `registry.redhat.io/rhaiis/vllm-cuda-rhel9@sha256:...` |
| `<GATEWAY_HOST>` | The maas-default-gateway external hostname (auto-assigned ELB or manually configured) | `a1b2c3.us-east-2.elb.amazonaws.com` |
| `<OGX_ROUTE>` | OGX external route hostname (if using OGX) | `ogx-route-redhat-ods-applications.apps.example.com` |
| `<SERVICE_NAME>` | LLMInferenceService name | `my-model-llmd` |

## Recommended Models

Choose a model that fits entirely on a single GPU — llm-d does not shard models across GPUs. Each replica loads the full model.

| Model | Size | Min GPU VRAM | Notes |
|-------|------|-------------|-------|
| `openai/gpt-oss-20b` | ~20B params | ~16 GB (quantized) | Tested with this guide on L4 (23GB) nodes |
| `meta-llama/Llama-3.1-8B-Instruct` | 8B params | ~8 GB (FP8) | Smaller model, works on most GPU types |
| `Qwen/Qwen2.5-0.5B-Instruct` | 0.5B params | any GPU / CPU | Used to verify this guide's batch and API examples; use the `-cpu` preset for CPU-only testing |

Set `<MODEL_URI>` to `hf://<model_name>` (e.g., `hf://openai/gpt-oss-20b`) and `<MODEL_NAME>` to the model identifier used in API requests (e.g., `openai/gpt-oss-20b`).

### vLLM image requirements

The `v1alpha2` presets pin a vLLM image digest, but published digests are
periodically removed from `registry.redhat.io`. If the workload pod reports
`ErrImagePull` ("manifest unknown"), override the image in `spec.template`
with the current digest from the [Red Hat Ecosystem Catalog](https://catalog.redhat.com/en/software/containers/rhaiis/vllm-cuda-rhel9/6825c6b827e18fe3162148a9).

Version floor: the Anthropic-compatible `/v1/messages` endpoint and current
tool-call parsers require a recent vLLM (verified with
`vllm-0.24.0+rhaiv.16` from the `rhais/vllm-cuda-rhel9` image). For CPU-only
testing, use the `rhais/vllm-cpu-rhel9` image with the
`v3-6-0-kserve-config-llm-template-cpu` preset.

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

Deploy the LLMInferenceService in the `redhat-ods-applications` namespace. This is required because the gateways only allow routes from this namespace.

A ready-to-use YAML template is at [`infrastructure/llm-d/llminferenceservice.yaml`](../infrastructure/llm-d/llminferenceservice.yaml). Edit the placeholders and apply:

```bash
oc apply -f infrastructure/llm-d/llminferenceservice.yaml
```

The template uses the **v1alpha2 API with `baseRefs`** — the preset supplies
the vLLM launch command (including TLS and the multi-tenant
`publishers/...` model names), health probes, and security context. Discover
the presets available on your cluster (names are version-prefixed):

```bash
oc get llminferenceserviceconfigs -n redhat-ods-applications
```

Key points:

- **`spec.router.scheduler: {}` must be explicitly set.** Without it, the controller skips scheduler/router creation and you get vLLM pods but no intelligent routing.
- **Gateway choice:** The template uses `maas-default-gateway` instead of `data-science-gateway`. The `data-science-gateway` has an OAuth proxy designed for browser access, which blocks programmatic API calls. The `maas-default-gateway` has no OAuth proxy and is suitable for API clients like OGX.
- **GPU taint:** The template includes a toleration for the `nvidia.com/gpu=true:NoSchedule` taint applied by the NVIDIA GPU Operator.

## Step 4: Create Network Policies

The default RHOAI network policy blocks port 8000. Apply the required network policies:

```bash
oc apply -f infrastructure/llm-d/network-policies.yaml
```

See [`infrastructure/llm-d/network-policies.yaml`](../infrastructure/llm-d/network-policies.yaml) for details.

## Step 5: Configure OGX (Optional)

If integrating with OGX, set these environment variables in your OGX deployment:

| Variable | Value | Notes |
|----------|-------|-------|
| `VLLM_URL` | `http://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1` | Must end with `/v1` — the OpenAI SDK appends `/models`, `/chat/completions`, etc. to this base URL |
| `VLLM_TLS_VERIFY` | `false` | Required when using self-signed certs |
| `VLLM_API_KEY` | *(leave empty)* | Not needed — the maas-default-gateway has no auth |

To find your `<GATEWAY_HOST>`:

```bash
oc get llminferenceservice <SERVICE_NAME> -n redhat-ods-applications -o jsonpath='{.status.url}'
```

If deploying OGX in the same namespace with an external route, apply the OGX network policy from `network-policies.yaml` to allow ingress from the OpenShift router.

## API Surfaces

Each LLMInferenceService is reachable through the auto-created HTTPRoute on
four API surfaces, plus multi-tenant publisher paths. All examples below use:

```bash
GW=https://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>
```

### Chat completions (OpenAI-compatible)

```bash
curl -s $GW/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'
```

### Completions and Responses API

`/v1/completions` (legacy) and `/v1/responses` (the newer Responses API used
by OpenAI SDKs and OGX) are routed the same way:

```bash
curl -s $GW/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","input":"Who wrote Moby Dick?"}'
```

### Messages API (Anthropic-compatible)

New in RHOAI 3.6: the gateway routes `/v1/messages`, vLLM's
Anthropic-compatible API, so Anthropic SDK clients work directly:

```bash
curl -s $GW/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"<MODEL_NAME>","max_tokens":20,"messages":[{"role":"user","content":"Say hello in one word"}]}'
```

The response is Anthropic-format (`{"type":"message","role":"assistant","content":[{"type":"text",...}]}`).

### Tool calling

Tool calling must be enabled at serve time via vLLM flags in
`VLLM_ADDITIONAL_ARGS` (see the template):

```text
--tool-call-parser=<parser> --enable-auto-tool-choice
```

The parser must match the model family:

| Parser | Model families |
|--------|----------------|
| `openai` | GPT-OSS and other OpenAI-native tool-call formats |
| `hermes` | Qwen 2.5/3, Hermes-function-calling models |
| `llama3_json` | Llama 3.1/3.3 |
| `mistral` | Mistral (7B instruct v0.2+, Small, Large) |
| `granite` | IBM Granite 3.x |
| `pythonic` | Models emitting native Python tool calls (some GLM/Kimi variants) |

Red Hat validates tool-calling capability for select models (GLM, Kimi, and
Inkling-Small families were validated with BFCL v4 for RHOAI 3.6). For models
without a validated parser, expect degraded or non-functional tool calls —
test with a simple two-tool request before building on it:

```bash
curl -s $GW/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<MODEL_NAME>",
    "max_tokens": 100,
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
      }
    }],
    "messages": [{"role": "user", "content": "What is the weather in Boston?"}]
  }'
```

A working response contains `choices[0].message.tool_calls` with
`finish_reason: "tool_calls"`.

### Multi-tenant model paths

Every model is also served under publisher (tenant) paths, which is how the
MaaS multi-tenancy model addresses models across namespaces:

```text
https://<GATEWAY_HOST>/publishers/<namespace>/models/<MODEL_NAME>/v1/chat/completions
```

For example:

```bash
curl -s https://<GATEWAY_HOST>/publishers/redhat-ods-applications/models/qwen/Qwen2.5-0.5B-Instruct/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
```

The model also appears under this publisher name in `/v1/models` output.

## Batch Inference

New in RHOAI 3.6: the llm-d batch gateway provides OpenAI-compatible
`/v1/batches` and `/v1/files` endpoints for high-volume, latency-agnostic
workloads (bulk classification, RAG corpus ingestion, nightly summarization).
Clients upload a JSONL file of requests, create a batch, disconnect, and
retrieve results when processing completes.

Everything below was verified end-to-end on RHOAI 3.6. Manifests are in
[`infrastructure/llm-d/`](../infrastructure/llm-d/):

| File | Purpose |
|------|---------|
| [`batch-deps.yaml`](../infrastructure/llm-d/batch-deps.yaml) | Dev-grade Redis + PostgreSQL backing services |
| [`batch-internal-gateway.yaml`](../infrastructure/llm-d/batch-internal-gateway.yaml) | Cluster-internal Gateway for processor → model traffic |
| [`batch-llm-route.yaml`](../infrastructure/llm-d/batch-llm-route.yaml) | HTTPRoute from the internal gateway to the InferencePool |
| [`llmbatchgateway.yaml`](../infrastructure/llm-d/llmbatchgateway.yaml) | PVC, credentials Secret, and the LLMBatchGateway CR |

### Step 1: Enable the batch gateway component

```bash
oc patch dsc default-dsc --type merge \
  -p '{"spec":{"components":{"aigateway":{"managementState":"Managed","batchGateway":{"managementState":"Managed"}}}}}'
```

Wait for the `llm-d-batch-gateway-operator` pod in `redhat-ods-applications`
and the `llmbatchgateways.batch.llm-d.ai` CRD. The operator deploys the
apiserver, processor, and garbage collector only after you create an
`LLMBatchGateway` CR — and it does **not** provision Redis or PostgreSQL;
bring your own.

### Step 2: Deploy backing services

The batch gateway needs Redis (request/result queues) and PostgreSQL (job
metadata). A dev-grade pair is in `batch-deps.yaml`:

```bash
oc apply -f infrastructure/llm-d/batch-deps.yaml
```

For production, use a managed or highly available Redis/Valkey and PostgreSQL.

### Step 3: Create the internal gateway and route

The async processor dispatches inference requests through a Gateway API
HTTPRoute to your service's InferencePool. Create a cluster-internal
(HTTP, ClusterIP) gateway and a route:

```bash
oc apply -f infrastructure/llm-d/batch-internal-gateway.yaml
oc apply -f infrastructure/llm-d/batch-llm-route.yaml   # edit <SERVICE_NAME> first
```

> **Important:** the route must match the **bare** API path
> (`/v1/chat/completions`). The dispatcher joins the per-request `url` field
> from the batch input JSONL with the gateway base URL, and the per-request
> endpoint takes precedence over the queue's configured path — a route that
> only matches `/<namespace>/<service>/v1/...` makes every batch request fail
> with 404.

### Step 4: Create the LLMBatchGateway

Edit `<MODEL_NAME>` and `<SERVICE_NAME>` in `llmbatchgateway.yaml`, then:

```bash
oc apply -f infrastructure/llm-d/llmbatchgateway.yaml
```

Wait until the gateway is ready:

```bash
oc get llmbatchgateway batch-gateway -n redhat-ods-applications
# Expected: READY True — apiserver, processor, GC, and async processor pods running
```

Notes on the CR:

- `processor.asyncConfig.resultPollTimeout` is **required** — the operator rejects the CR without it.
- `fileStorage.fs` with an RWO PVC is dev-grade: the apiserver, processor, and GC pods all mount the PVC, and with an RWO volume they must land on the **same node**. The scheduler does not guarantee this — pods that lose the volume race stay in `ContainerCreating` with `Multi-Attach error` events. If that happens, recover by pinning scheduling to the node that holds the volume (the node of the running `batch-gateway-processor-0` pod) and deleting the stuck pods:

  ```bash
  VOLUME_NODE=$(oc get pod batch-gateway-processor-0 -n redhat-ods-applications \
    -o jsonpath='{.spec.nodeName}')
  if [ -z "$VOLUME_NODE" ]; then
    echo "ERROR: batch-gateway-processor-0 not found or not scheduled — aborting" >&2
    exit 1
  fi
  # Cordon every schedulable node except the volume node, labeling the ones
  # this procedure cordons so already-cordoned nodes are left untouched.
  for n in $(oc get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'); do
    if [ "$n" != "$VOLUME_NODE" ] && \
       [ "$(oc get node "$n" -o jsonpath='{.spec.unschedulable}')" != "true" ]; then
      oc label node "$n" batch-recovery-cordoned=true --overwrite
      oc adm cordon "$n"
    fi
  done
  oc delete pod -n redhat-ods-applications -l app.kubernetes.io/instance=batch-gateway \
    --field-selector=status.phase!=Running
  # Uncordon only the nodes this procedure cordoned.
  for n in $(oc get nodes -l batch-recovery-cordoned=true \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'); do
    oc adm uncordon "$n"
    oc label node "$n" batch-recovery-cordoned-
  done
  ```

  For production, avoid the issue entirely: use an RWX PVC or the `s3` fileStorage backend. The example uses RWO because default storage classes on ROSA and self-managed AWS clusters (`gp2`/`gp3`) are RWO-only — RWX requires an additional storage layer such as OpenShift Data Foundation. If your cluster already has an RWX storage class, prefer it: change the PVC's `accessModes` to `ReadWriteMany` and skip the co-location recovery entirely.
- The operator creates an HTTPRoute exposing `/v1/batches` and `/v1/files` on the external gateway you specify in `spec.httpRoute.parentRefs`.

### Step 5: Run a batch

Create a JSONL input file — each line is one request, with `url` set to the
API path (bare path; the model goes in `body.model`):

```bash
cat > input.jsonl <<'EOF'
{"custom_id": "req-1", "method": "POST", "url": "/v1/chat/completions", "body": {"model": "<MODEL_NAME>", "messages": [{"role": "user", "content": "What is Kubernetes?"}], "max_tokens": 30}}
{"custom_id": "req-2", "method": "POST", "url": "/v1/chat/completions", "body": {"model": "<MODEL_NAME>", "messages": [{"role": "user", "content": "Explain KV cache."}], "max_tokens": 30}}
EOF
```

Upload the file, create the batch, poll, and download results:

```bash
GW=https://<GATEWAY_HOST>

# 1. Upload the input file
FILE_ID=$(curl -s $GW/v1/files -F "purpose=batch" -F "file=@input.jsonl" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 2. Create the batch
BATCH_ID=$(curl -s $GW/v1/batches -H "Content-Type: application/json" \
  -d "{\"input_file_id\": \"$FILE_ID\", \"endpoint\": \"/v1/chat/completions\", \"completion_window\": \"24h\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 3. Poll until status is "completed" (or "failed"/"expired")
watch curl -s $GW/v1/batches/$BATCH_ID

# 4. Download the results (JSONL: one response object per input line)
curl -sL $GW/v1/files/$(curl -s $GW/v1/batches/$BATCH_ID \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['output_file_id'])")/content
```

Each output line contains `custom_id`, `response.status_code`, and the full
response `body` (including `usage`). Batches can also be cancelled
(`POST /v1/batches/{id}/cancel`) before completion.

## Verification

### Check deployment status

```bash
# LLMInferenceService should show Ready: True
oc get llminferenceservice -n redhat-ods-applications

# Expected: N vLLM pods (1/1 Running) + 1 router-scheduler pod (1/1 Running)
oc get pods -n redhat-ods-applications | grep <SERVICE_NAME>

# InferencePool should exist
oc get inferencepool -n redhat-ods-applications
```

### Test inference

```bash
# Direct to llm-d gateway
curl -s https://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'

# Through OGX (if configured)
curl -s https://<OGX_ROUTE>/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","input":"Who is the president of the United States?"}'
```

### Test traffic distribution

Use the included test script to validate llm-d's intelligent routing:

```bash
uv run --with aiohttp python infrastructure/llm-d/test_distribution.py \
  --url https://<GATEWAY_HOST>/redhat-ods-applications/<SERVICE_NAME>/v1 \
  --model <MODEL_NAME>
```

See [`infrastructure/llm-d/test_distribution.py`](../infrastructure/llm-d/test_distribution.py) for details.

## Key Notes

- **llm-d is a routing/orchestration layer.** Each vLLM instance holds a complete copy of the model. llm-d routes requests intelligently (prefix-cache-aware, queue-based, active-request scoring) rather than round-robin.
- **LLMInferenceService** is the RHOAI-native way to deploy llm-d. It manages vLLM pods, the scheduler, InferencePool, and HTTPRoutes automatically. In 3.6, use the `v1alpha2` API and `baseRefs` presets instead of hand-writing the vLLM launch command and probes.
- **`router.scheduler: {}` is still required** in 3.6 — without it you get vLLM pods but no intelligent routing.
- **Use `maas-default-gateway`** for programmatic/API access. The `data-science-gateway` has an OAuth proxy meant for browser access.
- **Custom NetworkPolicies are required.** The default RHOAI network policy blocks port 8000, which vLLM uses for serving.
- **Choose a model that fits on a single GPU.** llm-d does not shard models across GPUs — each replica needs the full model in VRAM. (Disaggregated prefill/decode presets exist in 3.6 for advanced setups.)
- **Tool calling needs the right parser.** Serve with `--tool-call-parser=<family parser> --enable-auto-tool-choice`; see the [parser table](#tool-calling).
- **Batch gateway does not provision its dependencies.** Bring your own Redis, PostgreSQL, and file storage (RWX PVC or S3 for production — with a dev RWO PVC, the mounting pods must co-locate on one node; see the recovery procedure in the batch section). The batch HTTPRoute must match bare API paths (`/v1/chat/completions`) — the per-request `url` in the input JSONL overrides the queue's configured path.
- **The `maas-default-gateway` must exist before MaaS reconciles.** The `aigateway` DSC component does not create it — apply [`infrastructure/llm-d/maas-gateway.yaml`](../infrastructure/llm-d/maas-gateway.yaml) on clusters where no model was deployed through the dashboard.
- **MaaS multi-tenancy** addresses every model under `/publishers/<namespace>/models/<model>/v1/...` in addition to the service path.
