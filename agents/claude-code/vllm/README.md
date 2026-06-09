# vLLM Standalone Infrastructure

Deploy vLLM standalone on OpenShift for use with Claude Code (no OGX, no llm-d). This is the simplest architecture — a single vLLM pod serving the Anthropic Messages API directly.

## Contents

| File | Description |
|------|-------------|
| [`vllm-deployment.yaml`](vllm-deployment.yaml) | vLLM Deployment + Service template (replace placeholders before applying) |
| [`vllm-network-policy.yaml`](vllm-network-policy.yaml) | NetworkPolicy restricting ingress to OpenShift router and same namespace |
| [`tests/test_vllm_endpoints.sh`](tests/test_vllm_endpoints.sh) | Validates vLLM's OpenAI and Anthropic API endpoints (8 tests) |
| [`tests/test_claude_code_matrix.sh`](tests/test_claude_code_matrix.sh) | Tests Claude Code CLI functionality via `oc exec` (5 tests) |
| [`tests/test_vllm_latency.sh`](tests/test_vllm_latency.sh) | Latency and throughput benchmark (10 tests, outputs JSON) |

## Quick Start

See the full deployment guide: [docs/claude-code-vllm-direct.md](../../../docs/claude-code-vllm-direct.md)

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
