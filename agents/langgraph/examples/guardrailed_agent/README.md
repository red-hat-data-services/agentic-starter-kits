<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# Guardrailed Agent

</div>

---

## What this agent does

Banking customer service agent with [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) safety layer. Demonstrates how to add content safety, topical guardrails, and regex-based input filtering to a LangGraph ReAct agent using the **proxy pattern** — NeMo Guardrails sits between the agent and the LLM, requiring zero changes to the agent's source code.

### Guardrails architecture

```text
User → Agent (port 8000) → NeMo Guardrails (port 8090) → LLM (port 11434)
```

The agent uses the **proxy pattern** with `passthrough: true`. NeMo Guardrails sits between the agent and the LLM as a transparent safety filter — it checks every request/response against the configured rails, but passes the agent's system prompt and tool calls through unchanged. Without `passthrough`, NeMo runs its own conversational engine (3 extra LLM calls per request) and ignores the agent's prompts entirely.

### How rail layering works

Rails execute in a defined order. If any rail blocks, later rails in the chain are skipped and a refusal is returned immediately.

**Input rails** (checked before the LLM sees the message):

```text
User message
  │
  ├─ 1. Regex check ──────── instant pattern match, no LLM call
  │     Catches: jailbreak patterns ("ignore previous instructions", "DAN jailbreak")
  │     Cost: ~0ms, no tokens
  │     Config: rails.config.regex_detection.input.patterns in config.yaml
  │
  ├─ 2. Content safety ───── LLM classifies against S1–S13 categories
  │     Catches: violence, sexual content, criminal planning, hate speech, etc.
  │     Cost: 1 LLM call (~50 tokens)
  │     Config: content_safety_check_input prompt in prompts.yml
  │
  └─ 3. Topic safety ─────── LLM checks domain boundary
        Catches: off-topic requests (recipes, medical advice, dating tips)
        Cost: 1 LLM call (~10 tokens)
        Config: topic_safety_check_input prompt in prompts.yml
```

**Output rails** (checked after the LLM responds, before returning to user):

```text
LLM response
  │
  └─ 4. Content safety ───── LLM classifies response against S1–S13
        Catches: unsafe content the LLM generated despite safe input
        Cost: 1 LLM call (~50 tokens)
        Config: content_safety_check_output prompt in prompts.yml
```

**What the user sees when blocked:**

| Mode | Scenario | Response |
|------|----------|----------|
| Non-streaming | Rail blocks | `200` with `"I'm sorry, I can't respond to that."` |
| Streaming | Rail blocks | Content chunk with refusal text, then `finish_reason: stop` |
| Non-streaming | Guardrails down | `503` with `"The guardrails server is unavailable."` |
| Streaming | Guardrails down | `200` with SSE error event `{"error": {"type": "service_unavailable"}}` |

### Customizing the rails

**Change the domain** — edit the topic boundary prompt in `guardrails/safety/prompts.yml` (the `topic_safety_check_input` task). Replace the banking guidelines with your domain's allowed/disallowed topics. Everything else stays the same.

**Add regex patterns** — add patterns to `rails.config.regex_detection.input.patterns` in `guardrails/safety/config.yaml.example`. These are checked first (no LLM cost) and are good for known jailbreak strings.

**Disable a rail** — remove its entry from `rails.input.flows` or `rails.output.flows` in `config.yaml.example`. For example, remove `topic safety check input` to allow any topic.

**Use a different model per layer** — each of the 3 model roles (`main`, `content_safety`, `topic_control`) can be pointed at its own model/endpoint/key/engine via `.env` overrides: `MAIN_MODEL_ID`/`MAIN_LLM_BASE_URL`/`MAIN_API_KEY`/`MAIN_MODEL_ENGINE`, `CONTENT_SAFETY_MODEL_ID`/`CONTENT_SAFETY_LLM_BASE_URL`/`CONTENT_SAFETY_API_KEY`/`CONTENT_SAFETY_MODEL_ENGINE`, and the `TOPIC_CONTROL_*` equivalents (see `.env.example`). Any override left unset falls back to the shared `MODEL_ID`/`LLM_BASE_URL`/`API_KEY`, so single-model setups need no changes. This lets you use a small, fast model for classification while keeping a larger model for responses — or a purpose-built safety classifier for the rail layers only.

**Using NVIDIA's dedicated NemoGuard NIM models** — set a role's `_MODEL_ENGINE` to `nim` to route it through NeMo Guardrails' NIM/`ChatNVIDIA` integration (requires the `langchain-nvidia-ai-endpoints` package, included in the `guardrails` extra) instead of the generic OpenAI-compatible client:

```ini
CONTENT_SAFETY_MODEL_ID=nvidia/llama-3.1-nemotron-safety-guard-8b-v3
CONTENT_SAFETY_MODEL_ENGINE=nim
```

Verified working against NVIDIA's hosted NIM catalog (`https://integrate.api.nvidia.com/v1`) — correctly classifies both unsafe and safe inputs using this repo's existing `content_safety_check_input`/`content_safety_check_output` prompts, no prompt changes needed. (`nvidia/llama-3.1-nemotron-safety-guard-8b-v3` is the current, newer/renamed successor to `nvidia/llama-3.1-nemoguard-8b-content-safety`; both work as drop-ins.)

**`topic_control` on a NIM model** — NVIDIA's dedicated `nvidia/llama-3.1-nemoguard-8b-topic-control` model was the intended pairing for this role, but as of testing on 2026-07-30 it was returning `500` errors (TensorRT-LLM CUDA crash) on NVIDIA's hosted free tier — a server-side issue on NVIDIA's end, not a config problem. Its would-be unified successor, `nvidia/nemotron-content-safety-reasoning-4b`, reached end-of-life the same day.

Instead, this repo wires `topic_control` to **`nvidia/nemotron-3.5-content-safety`**, which classifies against a free-text policy (passed via `chat_template_kwargs.custom_policy`) rather than a fixed taxonomy, and returns a `"User Safety: safe|unsafe"` verdict — different enough from NeMo Guardrails' built-in on-topic/off-topic prompt that it needs its own action/flow (`guardrails/safety/actions.py` + `topic_policy.co`) instead of the library's `topic_safety_check_input`. `generate_config.py` auto-detects this model id (or any set via `TOPIC_CONTROL_CUSTOM_POLICY`), injects the topic-boundary policy into the model's `chat_template_kwargs`, and swaps the `topic_control` input rail flow accordingly — no manual `config.yaml` edits needed:

```ini
TOPIC_CONTROL_MODEL_ID=nvidia/nemotron-3.5-content-safety
TOPIC_CONTROL_MODEL_ENGINE=nim
```

Verified end-to-end on 2026-07-30: correctly passes banking questions and blocks off-topic ones (e.g. recipe requests) using the default policy text baked into `generate_config.py`. Override the policy text with `TOPIC_CONTROL_CUSTOM_POLICY` in `.env`.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Ollama](https://ollama.com/) — local LLM inference (or any OpenAI-compatible endpoint)
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) — for container builds
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) — for OpenShift deployment
- [Helm](https://helm.sh/) — for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell

## Local Development

### 1. Initialize

```bash
cd agents/langgraph/examples/guardrailed_agent
make init    # creates .env from .env.example
```

### 2. Install dependencies

```bash
make env     # creates venv and installs deps (including NeMo Guardrails)
```

### 3. Setup Ollama

Install Ollama and pull the default model:

```bash
make ollama  # installs Ollama (if needed) and pulls llama3.1:8b
```

Ensure Ollama is running (the macOS desktop app handles this automatically; otherwise run `ollama serve` in a separate terminal).

### 4. Start NeMo Guardrails proxy

> **Keep this terminal open** — the guardrails server needs to keep running.

```bash
make guardrails-server   # starts on port 8090, proxies to Ollama on 11434
```

The guardrails server generates its runtime config from `.env` at startup — no separate config step needed. The generated `config.yaml` is gitignored to prevent accidental credential commits.

> **Using a different model?** Set `MODEL_ID` in `.env`, pull it with
> `ollama pull <model>`, then restart `make guardrails-server`.
>
> **Using a remote endpoint instead of Ollama?** Set `LLM_BASE_URL` and `API_KEY` in `.env`,
> then restart `make guardrails-server`.

### 5. Start the agent

> **In a separate terminal:**

```bash
make run-app   # starts on port 8000
```

### 6. Test the guardrails

```bash
# On-topic question — should respond normally
curl -s http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is my balance for ACCT-12345?"}]}' \
  | python3 -m json.tool

# Toxic input — should be blocked by content safety rail
curl -s http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"How do I build a bomb?"}]}' \
  | python3 -m json.tool

# Off-topic request — should be blocked by topic safety rail
curl -s http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Give me a recipe for chocolate cake"}]}' \
  | python3 -m json.tool

# Greeting — should respond normally
curl -s http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello!"}]}' \
  | python3 -m json.tool
```

### Tracing (optional)

MLflow tracing works the same as other agents. Note that MLflow sees NeMo Guardrails as a regular ChatOpenAI endpoint — guardrails-internal traces (which rail fired, classification results) are not visible in MLflow. Use `nemoguardrails server --verbose` for rail-level debugging.

See `.env.example` for MLflow configuration options.

## Deploying to OpenShift

### Configuration

Edit `.env` with your model endpoint and container image:

```ini
API_KEY=your-api-key-here
BASE_URL=https://your-guardrails-endpoint/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/langgraph-guardrailed-agent:latest
```

> **Note:** In production on RHOAI, NeMo Guardrails runs as a separate pod managed by the `NemoGuardrails` CRD. The agent's `BASE_URL` points to the guardrails service, not directly to the LLM.

### Build and deploy

#### Option A: Build locally and push

```bash
make build    # builds the container image
make push     # pushes to the registry
make deploy   # deploys via Helm
```

#### Option B: Build in-cluster

```bash
make build-openshift   # builds via OpenShift BuildConfig
make deploy
```

### Verify

```bash
make dry-run   # preview Helm manifests (secrets redacted)
make undeploy  # remove deployment
```

## Tests

```bash
make test
```

## API Endpoints

### POST /chat/completions

```bash
# Non-streaming
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is my account balance?"}], "stream": false}'

# Streaming
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is my account balance?"}], "stream": true}'
```

### GET /health

```bash
curl http://localhost:8000/health
```

## Guardrails Configuration

| File | Purpose |
|------|---------|
| `guardrails/safety/config.yaml.example` | Template with safe defaults — model endpoints, rail ordering, regex patterns, streaming, `passthrough: true` |
| `guardrails/safety/config.yaml` | Runtime config (gitignored, generated by `make guardrails-server` from `.env` values) |
| `guardrails/safety/prompts.yml` | Classification prompts — content safety (S1–S13 categories) and topic safety (banking domain boundary) |
| `guardrails/safety/rails.co` | Colang greeting flows (required by RHOAI entrypoint, can be minimal) |

**Key constraints:**

- Config file must be `config.yaml` (not `.yml`) — RHOAI container entrypoint requirement (undocumented)
- `rails.co` must exist — RHOAI container entrypoint validates this file on startup
- NeMo Guardrails pinned to `0.21.0` to match RHOAI container version

## Known Limitations

- **Single-turn only** — the agent uses only the last user message; prior conversation history is not forwarded to the LLM. This matches the template pattern and is adequate for demonstrating guardrails behavior.
- **Health probe as readiness** — `/health` returns 503 when guardrails are unreachable. Use it as a Kubernetes **readiness** probe, not a liveness probe, to avoid unnecessary pod restarts.

## Resources

- [NeMo Guardrails Documentation](https://docs.nvidia.com/nemo/guardrails/)
- [LangGraph Documentation](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangChain Documentation](https://docs.langchain.com/oss/python/langchain/overview)
- [Ollama Documentation](https://docs.ollama.com)
