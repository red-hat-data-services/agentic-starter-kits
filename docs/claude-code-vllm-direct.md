# Claude Code with vLLM Direct (No OGX)

Deploy Claude Code on OpenShift pointing directly at vLLM's `/v1/messages` endpoint, bypassing OGX entirely. This is the simplest architecture for running Claude Code against a self-hosted model.

For the OGX-based setup (multi-backend routing, model aliasing at the gateway layer), a separate guide will be provided once OGX support is available.

## Architecture

```text
Claude Code pod  ──HTTP──▶  vLLM service (ClusterIP :8000)
                             └── /v1/messages (Anthropic Messages API)
```

No OGX, no translation layer. vLLM natively serves the Anthropic Messages API format.

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| **OpenShift cluster** | With GPU nodes available (e.g., `g6e.12xlarge` for 4x L40S) |
| **GPU node pool** | Labeled for scheduling (e.g., `node-pool=gpu-g6e-12xl`) |
| **Model with 32K+ context** | Claude Code's system prompt is ~20K+ tokens. Models with 16K or less will fail. Recommended: 64K+ for multi-turn conversations. |
| **`oc` CLI** | Logged into the target OpenShift cluster |
| **Claude Code build files** | `Containerfile`, `entrypoint.sh`, `deployment.yaml` from [`agents/claude-code/deployment/`](../agents/claude-code/deployment/) |

## Configuration Reference

Before deploying, replace the following placeholders in the manifest files:

| Variable | Description | Example |
|----------|-------------|---------|
| `<NAMESPACE>` | Namespace for vLLM and Claude Code | `redhat-ods-applications` |
| `<MODEL_NAME>` | Model identifier from `/v1/models` | `openai/gpt-oss-120b` |
| `<MODEL_SHORT_NAME>` | Short name for K8s resources | `gpt-oss-120b` |
| `<NODE_POOL>` | GPU node pool label | `gpu-g6e-12xl` |
| `<TP_SIZE>` | Tensor parallel size (number of GPUs) | `4` |
| `<MAX_MODEL_LEN>` | Max context length | `131072` |

## Step 1: Deploy vLLM

The deployment manifest is at [`agents/claude-code/vllm/vllm-deployment.yaml`](../agents/claude-code/vllm/vllm-deployment.yaml). It deploys vLLM as a standalone Deployment — no storage-initializer sidecar, vLLM downloads the model directly at startup.

The vLLM image is from RHOAI (vLLM `0.13.0+rhai19`). Check your RHOAI version for the matching image tag — different RHOAI releases ship different vLLM versions.

Replace the placeholders and apply:

```bash
# Edit the placeholders in the manifest first, then apply
oc apply -f agents/claude-code/vllm/vllm-deployment.yaml -n <NAMESPACE>
```

Wait for the model to download and load (10–30 minutes for large models):

```bash
oc rollout status deployment/<MODEL_SHORT_NAME> -n <NAMESPACE>
oc logs -f deployment/<MODEL_SHORT_NAME> -n <NAMESPACE>
```

**Key settings in the manifest:**

- `HF_HUB_ENABLE_HF_TRANSFER=0` — use standard HTTP downloads. The HF Xet high-performance downloader can stall on large models (60GB+) in cluster environments.
- `NCCL_IB_DISABLE=1` — disables InfiniBand (not available on standard GPU instance types like g6e).
- `/dev/shm` at 16Gi — required for NCCL multi-GPU communication with tensor parallelism.
- `readinessProbe` on `/health` — required for OpenShift routes to forward traffic.

## Step 2: Create External Route

Apply the network policy from [`agents/claude-code/vllm/vllm-network-policy.yaml`](../agents/claude-code/vllm/vllm-network-policy.yaml) and create an external route:

```bash
# Network policy — restricts ingress to router and same namespace
oc apply -f agents/claude-code/vllm/vllm-network-policy.yaml -n <NAMESPACE>

# External route (TLS edge termination)
oc create route edge <MODEL_SHORT_NAME>-external \
  --service=<MODEL_SHORT_NAME> --port=http -n <NAMESPACE>
```

## Step 3: Verify vLLM Endpoints

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

## Step 4: Deploy Claude Code

The Claude Code build files (`Containerfile`, `entrypoint.sh`, `deployment.yaml`) are in [`agents/claude-code/deployment/`](../agents/claude-code/deployment/). See the [Claude Code deployment README](../agents/claude-code/deployment/README.md) for the full build and deploy guide.

To point Claude Code at your vLLM service, set these env vars in the deployment manifest:

```yaml
env:
  - name: HOME
    value: "/home/claude-agent"
  - name: ANTHROPIC_API_KEY
    valueFrom:
      secretKeyRef:
        name: claude-credentials
        key: ANTHROPIC_API_KEY
  - name: ANTHROPIC_BASE_URL
    value: "http://<MODEL_SHORT_NAME>.<NAMESPACE>.svc.cluster.local:8000"
  - name: CLAUDE_MODEL
    value: "<MODEL_NAME>"
  - name: MCP_CONFIG_FILE
    value: "/etc/mcp/config.json"
  - name: SKIP_PERMISSIONS
    value: "true"
```

Since the standalone vLLM deployment serves plain HTTP (no TLS), `NODE_TLS_REJECT_UNAUTHORIZED` is not needed.

Create a dummy API key secret (vLLM doesn't validate it, but Claude Code requires the env var):

```bash
oc create secret generic claude-credentials \
  --from-literal=ANTHROPIC_API_KEY=dummy-key-for-vllm \
  -n <NAMESPACE>
```

### Smoke Test

```bash
oc exec deployment/claude-code -n <NAMESPACE> -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2? Reply with just the number."
'
```

## Testing

Test scripts are in [`agents/claude-code/vllm/tests/`](../agents/claude-code/vllm/tests/) to validate the full setup.

### vLLM Endpoint Validation

Tests vLLM's OpenAI and Anthropic API endpoints directly (no Claude Code). Requires only `curl` and `jq`.

```bash
bash agents/claude-code/vllm/tests/test_vllm_endpoints.sh \
  --url https://<VLLM_EXTERNAL_ROUTE> \
  --model <MODEL_NAME> \
  --insecure  # only if using self-signed certs
```

Tests: health check, model listing, OpenAI chat (streaming + non-streaming), Anthropic messages (streaming + non-streaming), multi-turn conversation, tool use.

### Claude Code Test Matrix

Tests Claude Code CLI functionality via `oc exec`. Requires `oc` logged into the cluster.

```bash
bash agents/claude-code/vllm/tests/test_claude_code_matrix.sh \
  --namespace <NAMESPACE> \
  --deployment claude-code
```

Tests: single-turn prompt, multi-step reasoning, bash tool use, file read tool use, CLI response verification.

### Latency Benchmark

Measures latency, TTFB, and throughput across request types. Results are saved to a timestamped JSON file for later comparison.

```bash
bash agents/claude-code/vllm/tests/test_vllm_latency.sh \
  --url https://<VLLM_EXTERNAL_ROUTE> \
  --model <MODEL_NAME> \
  --runs 3 \
  --output .
```

### Configuration

All scripts accept CLI flags or environment variables:

| Env Var | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `VLLM_URL` | `--url` | (required) | vLLM base URL |
| `VLLM_MODEL` | `--model` | (required) | Model name |
| `VLLM_API_KEY` | `--api-key` | `""` | API key (if auth enabled) |
| `VLLM_INSECURE` | `--insecure` | `false` | Disable TLS certificate verification |
| `VLLM_NAMESPACE` | `--namespace` | `redhat-ods-applications` | OpenShift namespace |
| `CLAUDE_DEPLOYMENT` | `--deployment` | `claude-code` | Claude Code deployment |
| `VLLM_TIMEOUT` | `--timeout` | `60` / `120` | Request timeout (seconds) |

## Model Aliasing

vLLM supports model aliasing via `--served-model-name`. This lets you serve a model under a custom name without OGX.

Add `--served-model-name` to the vLLM command in the deployment manifest:

```yaml
command:
  - python3
  - -m
  - vllm.entrypoints.openai.api_server
  - --model
  - openai/gpt-oss-120b
  - --served-model-name
  - my-custom-model-name
  # ... other flags
```

Then set `CLAUDE_MODEL` on the Claude Code pod to match:

```bash
oc set env deployment/claude-code CLAUDE_MODEL=my-custom-model-name
```

**Important behavior:**

- `--served-model-name` is a **replacement**, not an addition. The original HuggingFace model ID (`openai/gpt-oss-120b`) is no longer recognized after setting an alias.
- To keep both the original name and an alias, pass the flag twice: `--served-model-name openai/gpt-oss-120b --served-model-name my-alias`.
- No OGX is required for model aliasing — vLLM handles it natively.

## Known Limitations

### Context Window Requirement

Claude Code sends a large internal system prompt (~20K+ tokens) with every request. Models with insufficient context will fail:

```text
API Error: 400 {"type":"error","error":{"type":"BadRequestError",
"message":"max_tokens must be at least 1, got -7214."}}
```

**Minimum:** 32K tokens. **Recommended:** 64K+ for multi-turn conversations with tool use.

### LLMInferenceService vs Standalone Deployment

The KServe `LLMInferenceService` CRD adds a `storage-initializer` init container that uses HF Xet for model downloads. This can stall on large models (60GB+) due to CDN timeouts, and the CRD does not expose init container env overrides. The standalone Deployment approach (shown above) lets vLLM download the model directly with standard HTTP, which is more reliable.

Use `LLMInferenceService` when you need the llm-d router/scheduler for multi-replica intelligent routing. Use standalone Deployment for single-replica setups or when the init container stalls.

## Cleanup

```bash
# vLLM
oc delete deployment <MODEL_SHORT_NAME> -n <NAMESPACE>
oc delete service <MODEL_SHORT_NAME> -n <NAMESPACE>
oc delete route <MODEL_SHORT_NAME>-external -n <NAMESPACE>
oc delete networkpolicy allow-<MODEL_SHORT_NAME>-ingress -n <NAMESPACE>

# Claude Code
oc delete deployment claude-code -n <NAMESPACE>
oc delete buildconfig claude-code -n <NAMESPACE>
oc delete imagestream claude-code -n <NAMESPACE>
oc delete secret claude-credentials -n <NAMESPACE>
oc delete configmap claude-mcp-config claude-skills -n <NAMESPACE>
oc delete pvc claude-workspace -n <NAMESPACE>
oc delete service claude-code -n <NAMESPACE>
```

## Next Steps

- Latency comparison: direct vLLM vs. OGX translation vs. OGX passthrough (pending OGX availability)
