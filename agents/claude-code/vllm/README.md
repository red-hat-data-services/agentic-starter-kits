# vLLM Standalone Infrastructure

Deploy vLLM standalone on OpenShift for use with Claude Code (no OGX, no llm-d). This is the simplest architecture: a single vLLM pod serving the Anthropic Messages API directly.

For connecting Claude Code to this vLLM server, see the [Claude Code deployment guide](../README.md) (Option C: vLLM Direct).

## Contents

| File | Description |
|------|-------------|
| [`vllm-deployment.yaml`](vllm-deployment.yaml) | vLLM Deployment + Service template (replace placeholders before applying) |
| [`vllm-network-policy.yaml`](vllm-network-policy.yaml) | NetworkPolicy restricting ingress to OpenShift router and same namespace |
| [`tests/test_vllm_endpoints.sh`](tests/test_vllm_endpoints.sh) | Validates vLLM's OpenAI and Anthropic API endpoints (8 tests) |
| [`tests/test_claude_code_matrix.sh`](tests/test_claude_code_matrix.sh) | Tests Claude Code CLI functionality via `oc exec` (5 tests) |
| [`tests/test_vllm_latency.sh`](tests/test_vllm_latency.sh) | Latency and throughput benchmark (10 tests, outputs JSON) |

## Configuration Reference

Replace these placeholders in the manifest files before applying:

| Variable | Description | Example |
|----------|-------------|---------|
| `<NAMESPACE>` | Namespace for vLLM | `redhat-ods-applications` |
| `<MODEL_NAME>` | Model identifier from `/v1/models` | `openai/gpt-oss-120b` |
| `<MODEL_SHORT_NAME>` | Short name for K8s resources | `gpt-oss-120b` |
| `<NODE_POOL>` | GPU node pool label | `gpu-g6e-12xl` |
| `<TP_SIZE>` | Tensor parallel size (number of GPUs) | `4` |
| `<MAX_MODEL_LEN>` | Max context length | `131072` |

## Deploying vLLM

### Prerequisites

| Requirement | Description |
|-------------|-------------|
| **OpenShift cluster** | With GPU nodes available (e.g., `g6e.12xlarge` for 4x L40S) |
| **GPU node pool** | Labeled for scheduling (e.g., `node-pool=gpu-g6e-12xl`) |
| **Model with 32K+ context** | Claude Code's system prompt is ~23K tokens. 128K+ recommended for multi-turn work. |
| **`oc` CLI** | Logged into the target OpenShift cluster |

### Step 1: Deploy vLLM

Edit the placeholders in `vllm-deployment.yaml` and apply:

```bash
oc apply -f vllm-deployment.yaml -n <NAMESPACE>
```

Wait for the model to download and load (10 to 30 minutes for large models):

```bash
oc rollout status deployment/<MODEL_SHORT_NAME> -n <NAMESPACE>
oc logs -f deployment/<MODEL_SHORT_NAME> -n <NAMESPACE>
```

**Key settings in the manifest:**

- `HF_HUB_ENABLE_HF_TRANSFER=0`: use standard HTTP downloads. The HF Xet high-performance downloader can stall on large models (60GB+) in cluster environments.
- `NCCL_IB_DISABLE=1`: disables InfiniBand (not available on standard GPU instance types like g6e).
- `/dev/shm` at 16Gi: required for NCCL multi-GPU communication with tensor parallelism.
- `readinessProbe` on `/health`: required for OpenShift routes to forward traffic.

The vLLM image is from RHOAI (vLLM `0.13.0+rhai19`). Check your RHOAI version for the matching image tag.

### Step 2: Create External Route

Apply the network policy and create a TLS-terminated external route:

```bash
# Network policy: restricts ingress to router and same namespace
oc apply -f vllm-network-policy.yaml -n <NAMESPACE>

# External route (TLS edge termination)
oc create route edge <MODEL_SHORT_NAME>-external \
  --service=<MODEL_SHORT_NAME> --port=http -n <NAMESPACE>
```

### Step 3: Verify

```bash
VLLM_ROUTE=$(oc get route <MODEL_SHORT_NAME>-external -n <NAMESPACE> -o jsonpath='{.spec.host}')

# Health check
curl -s "https://$VLLM_ROUTE/health"

# List models
curl -s "https://$VLLM_ROUTE/v1/models"

# Non-streaming (Anthropic Messages API)
curl -s "https://$VLLM_ROUTE/v1/messages" \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","max_tokens":50,"messages":[{"role":"user","content":"Hello"}]}'

# Streaming (SSE)
curl -s "https://$VLLM_ROUTE/v1/messages" \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","max_tokens":50,"stream":true,"messages":[{"role":"user","content":"Hello"}]}'
```

The streaming response should include all SSE event types: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`.

## Running Tests

All scripts accept `--help` for full usage. Common options can be set via CLI flags or environment variables.

### vLLM Endpoint Validation

Validates health, model listing, OpenAI chat, Anthropic messages (streaming + non-streaming), multi-turn, and tool use:

```bash
bash tests/test_vllm_endpoints.sh \
  --url https://<VLLM_ROUTE> \
  --model <MODEL_NAME> \
  --insecure  # only if using self-signed certs
```

### Claude Code Test Matrix

Validates single-turn, multi-step reasoning, bash tool use, file read, and CLI response via `oc exec`:

```bash
bash tests/test_claude_code_matrix.sh \
  --namespace <NAMESPACE> \
  --deployment claude-code
```

### Latency Benchmark

Measures TTFB, total latency, and throughput across short/long prompts, streaming/non-streaming, and tool use. Results are saved to a timestamped JSON file:

```bash
bash tests/test_vllm_latency.sh \
  --url https://<VLLM_ROUTE> \
  --model <MODEL_NAME> \
  --runs 3 \
  --output .
```

### Environment Variables

| Env Var | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `VLLM_URL` | `--url` | (required) | vLLM base URL |
| `VLLM_MODEL` | `--model` | (required) | Model name |
| `VLLM_API_KEY` | `--api-key` | `""` | API key (if auth enabled) |
| `VLLM_INSECURE` | `--insecure` | `false` | Disable TLS certificate verification |
| `VLLM_NAMESPACE` | `--namespace` | `redhat-ods-applications` | OpenShift namespace |
| `CLAUDE_DEPLOYMENT` | `--deployment` | `claude-code` | Claude Code deployment |
| `VLLM_TIMEOUT` | `--timeout` | `60` / `120` | Request timeout (seconds) |

## Known Limitations

### LLMInferenceService vs Standalone Deployment

The KServe `LLMInferenceService` CRD adds a `storage-initializer` init container that uses HF Xet for model downloads. This can stall on large models (60GB+) due to CDN timeouts, and the CRD does not expose init container env overrides. The standalone Deployment approach (shown above) lets vLLM download the model directly with standard HTTP, which is more reliable.

Use `LLMInferenceService` when you need the llm-d router/scheduler for multi-replica intelligent routing. Use standalone Deployment for single-replica setups or when the init container stalls.

## Cleanup

```bash
oc delete deployment <MODEL_SHORT_NAME> -n <NAMESPACE>
oc delete service <MODEL_SHORT_NAME> -n <NAMESPACE>
oc delete route <MODEL_SHORT_NAME>-external -n <NAMESPACE>
oc delete networkpolicy allow-<MODEL_SHORT_NAME>-ingress -n <NAMESPACE>
```
