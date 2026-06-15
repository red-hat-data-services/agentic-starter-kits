# OGX Gateway for Claude Code

Deploy OGX as an API gateway between Claude Code and vLLM on OpenShift. OGX provides the Anthropic Messages API (`/v1/messages`) passthrough to vLLM.

## Architecture

```text
Claude Code  ──HTTP──▶  OGX (:8321)  ──HTTP──▶  vLLM (:8000)
                        /v1/messages              /v1/messages
                        (passthrough)             (Anthropic API)
```

When vLLM supports `/v1/messages` natively, OGX uses passthrough mode — requests are forwarded directly to vLLM without API format translation. If vLLM does not support `/v1/messages`, OGX falls back to translating Anthropic requests into OpenAI format via `/v1/chat/completions`.

## Prerequisites

- A vLLM server running and accessible within the cluster (see [`../vllm/`](../vllm/))
- The vLLM model must have a context window >= 32K tokens (Claude Code's system prompt is ~23K tokens). For realistic coding work, 128K+ tokens is strongly recommended since CLAUDE.md, skills, file listings, and conversation easily push input past 100K tokens
- `oc` CLI logged into the target OpenShift cluster

## Contents

| File | Description |
|------|-------------|
| [`ogx-configmap.yaml`](ogx-configmap.yaml) | OGX runtime configuration (APIs, providers, model registration) |
| [`ogx-deployment.yaml`](ogx-deployment.yaml) | OGX Deployment (standalone, no operator required) |
| [`ogx-service.yaml`](ogx-service.yaml) | ClusterIP Service for OGX |
| [`ogx-network-policy.yaml`](ogx-network-policy.yaml) | NetworkPolicy allowing ingress on port 8321 |

## Configuration Reference

Replace these placeholders in the manifest files before applying:

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `<VLLM_SERVICE>` | vLLM Kubernetes service name | `gpt-oss-120b` |
| `<NAMESPACE>` | Namespace where vLLM and OGX run | `redhat-ods-applications` |
| `<VLLM_PORT>` | vLLM service port | `8000` |
| `<MODEL_ID>` | Model name as registered in vLLM (`/v1/models`) | `my-custom-120b` |

## Quick Start

```bash
# 1. Edit ogx-configmap.yaml — replace placeholders with your values
# 2. Apply all manifests
oc apply -f ogx-configmap.yaml -n <NAMESPACE>
oc apply -f ogx-deployment.yaml -n <NAMESPACE>
oc apply -f ogx-service.yaml -n <NAMESPACE>
oc apply -f ogx-network-policy.yaml -n <NAMESPACE>

# 3. Wait for OGX to be ready
oc rollout status deployment/ogx -n <NAMESPACE>

# 4. Verify
oc exec deployment/ogx -- curl -s http://localhost:8321/v1/health
oc exec deployment/ogx -- curl -s http://localhost:8321/v1/models
```

## Connecting Claude Code to OGX

Set the following env vars on your Claude Code deployment:

```bash
oc set env deployment/claude-code \
  ANTHROPIC_BASE_URL=http://ogx-service.<NAMESPACE>.svc.cluster.local:8321 \
  CLAUDE_MODEL=vllm/<MODEL_ID>
```

OGX prefixes model IDs with the provider name (`vllm/`), so use `vllm/<MODEL_ID>` when configuring Claude Code.

For the full Claude Code deployment guide, see [`../README.md`](../README.md) (Option D covers OGX).

## Verifying the Passthrough

```bash
# Non-streaming
oc exec deployment/ogx -- curl -s http://localhost:8321/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"vllm/<MODEL_ID>","max_tokens":50,"messages":[{"role":"user","content":"Hello"}]}'

# Streaming (SSE)
oc exec deployment/ogx -- curl -s http://localhost:8321/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"vllm/<MODEL_ID>","max_tokens":50,"stream":true,"messages":[{"role":"user","content":"Hello"}]}'
```

The streaming response should include all SSE event types: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`.

## OGX Configuration Details

The `ogx-configmap.yaml` contains the OGX runtime configuration. Key sections:

### APIs

```yaml
apis:
- inference    # Enables /v1/chat/completions (OpenAI format)
- messages     # Enables /v1/messages (Anthropic format)
```

Both APIs are required. The `messages` API provides the Anthropic Messages API that Claude Code uses. The `inference` API provides the OpenAI-compatible backend that OGX routes to.

### Providers

```yaml
providers:
  inference:
  - provider_id: vllm
    provider_type: remote::vllm
    config:
      base_url: http://<VLLM_SERVICE>.<NAMESPACE>.svc.cluster.local:<VLLM_PORT>/v1
      api_token: fake        # vLLM does not validate API tokens
      max_tokens: 4096       # Default max tokens per request

  messages:
  - provider_id: builtin
    provider_type: inline::builtin   # Translates Anthropic ↔ OpenAI
```

The `remote::vllm` provider connects to your vLLM backend. The `inline::builtin` messages provider enables the `/v1/messages` endpoint — when vLLM supports it natively, OGX uses passthrough mode (no translation).

### Models

```yaml
models:
- model_id: <MODEL_ID>              # Name exposed via /v1/models
  provider_id: vllm                 # Routes to the vllm provider
  provider_model_id: <MODEL_ID>     # Name used when calling vLLM
  model_type: llm
```

The `model_id` is what clients use to request the model. OGX prefixes it with the provider name, so clients see `vllm/<MODEL_ID>` in the models list.

## Known Issues

### Service Name Collision

The OGX service must not be named `ogx`. Kubernetes auto-injects environment variables for each service (`<SERVICE_NAME>_PORT`, `<SERVICE_NAME>_HOST`, etc.). A service named `ogx` would inject `OGX_PORT=tcp://<ip>:8321`, which collides with OGX's internal `OGX_PORT` env var that expects an integer port number. The manifests use `ogx-service` to avoid this.

### Network Policy Required

A network policy is required to allow traffic to reach OGX on port 8321 from Claude Code and the OpenShift router. Apply `ogx-network-policy.yaml` before testing.

### Storage Backend

These manifests use SQLite (`/tmp/ogx.db`) for OGX's internal storage, which is suitable for single-replica deployments. For multi-replica or production setups, configure PostgreSQL as the storage backend in `ogx-configmap.yaml`.

## Cleanup

```bash
oc delete deployment ogx -n <NAMESPACE>
oc delete service ogx-service -n <NAMESPACE>
oc delete configmap ogx-config -n <NAMESPACE>
oc delete networkpolicy allow-ogx-ingress -n <NAMESPACE>
```
