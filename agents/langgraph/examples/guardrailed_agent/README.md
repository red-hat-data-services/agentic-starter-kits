<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# Guardrailed Agent

</div>

---

## What this agent does

FSI customer service agent with [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) safety layer. Demonstrates how to add content safety, topical guardrails, and regex-based input filtering to a LangGraph ReAct agent using the **proxy pattern** — NeMo Guardrails sits between the agent and the LLM, requiring zero changes to the agent's source code.

### Guardrails architecture

```text
User → Agent (port 8000) → NeMo Guardrails (port 8090) → LLM (port 11434)
```

Three layered input rails run in order (if any blocks, later rails are skipped):

1. **Regex** — instant pattern matching, no LLM call (catches jailbreak patterns)
2. **Content safety** — LLM classifies input against S1–S13 safety categories
3. **Topic safety** — LLM checks if input is within the banking domain boundary

Plus a content safety **output rail** that checks the LLM's response before returning it.

### Swapping the use case

The banking domain is defined entirely in `guardrails/safety/prompts.yml` (the `topic_safety_check_input` prompt). To adapt this example to a different domain (healthcare, telecom, etc.), edit only that prompt's guidelines list. Everything else stays the same.

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

### 4. Start OGX server

> **Keep this terminal open** — the OGX server needs to keep running.
> NeMo Guardrails will proxy LLM requests through OGX to Ollama.

```bash
make ogx-server  # starts on port 8321
```

### 5. Start NeMo Guardrails proxy

> **In a separate terminal.** Keep it open — the guardrails server needs to keep running.

```bash
make guardrails-server   # starts on port 8090, proxies to OGX on 8321
```

The guardrails server reads its config from `guardrails/safety/config.yaml`.

> **Using a different model?** Set `MODEL_ID` in `.env`, pull it with
> `ollama pull <model>`, then run `make guardrails-config` to update the guardrails config.
>
> **Using a remote endpoint instead of OGX?** Set `LLM_BASE_URL` in `.env` to your
> OpenAI-compatible endpoint, then run `make guardrails-config`.

### 6. Start the agent

> **In a separate terminal:**

```bash
make run-app   # starts on port 8000
```

### 7. Test the guardrails

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
| `guardrails/safety/config.yaml` | Model endpoints, rail ordering, streaming, regex patterns |
| `guardrails/safety/prompts.yml` | Content safety (S1–S13) and topic safety classification prompts |
| `guardrails/safety/rails.co` | Colang greeting flows (required by RHOAI entrypoint) |

**Key constraints:**

- Config file must be `config.yaml` (not `.yml`) — RHOAI container entrypoint requirement
- `rails.co` must exist — RHOAI container entrypoint requirement (can be minimal)
- NeMo Guardrails version pinned to `0.21.0` to match RHOAI

## Resources

- [NeMo Guardrails Documentation](https://docs.nvidia.com/nemo/guardrails/)
- [LangGraph Documentation](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangChain Documentation](https://docs.langchain.com/oss/python/langchain/overview)
- [Ollama Documentation](https://docs.ollama.com)
