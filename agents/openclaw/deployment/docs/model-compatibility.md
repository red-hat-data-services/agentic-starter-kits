# Model Compatibility for OpenClaw Tool-Calling

> Tested: 2026-04-13

OpenClaw relies on models that support structured tool-calling (function calling). Not all models work — some emit raw JSON instead of using the native tool API, and some hallucinate tool results when calls fail silently.

## Test Results

| Model | Provider | Tool-Calling | Notes |
|-------|----------|:------------:|-------|
| **gpt-oss-20b** | vLLM (cluster) | Working | `--tool-call-parser openai --enable-auto-tool-choice` flags required |
| **qwen2.5:7b** | Ollama (local) | Working | Best local option for 32GB machines (~8GB RAM) |
| **qwen3.5:27b** | Ollama (local) | Working | Tools work, but 41GB RAM usage makes it impractical locally |
| **llama3.2:3b** | Ollama (local) | Partial | Executes tools but gets confused by OpenClaw's internal system prompts |
| **phi4-mini:3.8b** | Ollama (local) | Broken | Emits raw JSON in response body instead of native tool calls |
| **codex/gpt-5.4** | Codex Harness | Expected | Routes through Codex app-server; requires sidecar deployment (see [codex-harness.md](codex-harness.md)) |

## Critical Warning: Hallucinated Tool Results

When phi4-mini's tool calls failed silently, the model **fabricated an entire file listing** — realistic-looking paths that did not exist on the machine, presented confidently as real data.

This is the most dangerous failure mode for an agentic system: the user has no way to know the results are fake without independently verifying every output.

## Provider Routing

OpenClaw supports multiple model providers simultaneously. The model reference prefix determines the routing:

| Prefix | Route | Harness |
|--------|-------|---------|
| `openai-compat/` | Self-hosted vLLM endpoint | OpenClaw PI runtime |
| `openai/` | Direct OpenAI API | OpenClaw PI runtime |
| `codex/` | Codex app-server (sidecar) | Codex harness |
| `anthropic/` | Anthropic API | OpenClaw PI runtime |
| `ollama/` | Local Ollama instance | OpenClaw PI runtime |

Mixed deployments can use `runtime: "auto"` to let OpenClaw select the harness based on model prefix.

## Recommendations

- **On OpenShift (self-hosted):** Use gpt-oss-20b or larger via vLLM with tool-calling flags enabled
- **On OpenShift (Codex):** Use `codex/gpt-5.4` with the Codex Harness sidecar for thread management and guardian approvals
- **On OpenShift (Google):** Use `google/gemini-2.5-pro` via Google AI Studio with `GEMINI_API_KEY` (Vertex AI SA auth is not yet supported natively — see [vertex-ai-provider.md](vertex-ai-provider.md#known-limitation-vertex-ai-auth))
- **Local testing:** Use qwen2.5:7b via Ollama with a 32k context window
- **Always verify:** Test tool-calling with a known-answer query (e.g., "list files on my Desktop") before trusting agent output

## Valid API Types

When configuring `models.providers.*.api` in the ConfigMap, use one of:

| API Type | Use Case |
|----------|----------|
| `openai-completions` | vLLM, LM Studio, any OpenAI-compatible endpoint |
| `openai-responses` | Direct OpenAI API |
| `openai-codex-responses` | Codex app-server |
| `anthropic-messages` | Anthropic API or Anthropic on Vertex AI |
| `google-generative-ai` | Google Gemini (AI Studio or Vertex AI) |
| `ollama` | Local Ollama instance |
| `azure-openai-responses` | Azure OpenAI |
| `bedrock-converse-stream` | AWS Bedrock |
| `github-copilot` | GitHub Copilot |
