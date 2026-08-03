<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# Guardrailed Agent

</div>

---

## What this agent does

Banking customer service agent with [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) safety layer. Demonstrates how to add content safety, topical guardrails, and regex-based input filtering to a LangGraph ReAct agent using the **proxy pattern** — NeMo Guardrails sits between the agent and the LLM, requiring zero changes to the agent's source code.

Two guardrails config profiles live side by side under `guardrails/config/`, matching two maturity levels of the same rail layering:

| Profile | Rails | Models | Use case |
|---------|-------|--------|----------|
| `local` | `self check input`/`self check output` (NeMo Guardrails built-in) | Single model — the same one answering the user's question also classifies it | Zero-setup local demo of the proxy pattern (`make guardrails-server-local`) |
| `nemoguard` | `content safety check`, `topic safety check`, regex | Purpose-built NemoGuard/Nemotron classifiers, one per rail layer | Dedicated safety models per layer (`make guardrails-server-nemoguard` locally, `make deploy-guardrails` on RHOAI); works against NVIDIA-hosted NIM today, or an in-cluster endpoint via the bundled `NemoGuardrails` CRD manifests |

### Guardrails architecture

```text
User → Agent (port 8000) → NeMo Guardrails (port 8090) → LLM (port 11434)
```

The agent uses the **proxy pattern** with `passthrough: true`. NeMo Guardrails sits between the agent and the LLM as a transparent safety filter — it checks every request/response against the configured rails, but passes the agent's system prompt and tool calls through unchanged. Without `passthrough`, NeMo runs its own conversational engine (3 extra LLM calls per request) and ignores the agent's prompts entirely.

### How rail layering works (nemoguard profile)

Rails execute in a defined order. If any rail blocks, later rails in the chain are skipped and a refusal is returned immediately. This describes the `nemoguard` profile's layering; the `local` profile is simpler — just `self check input` and `self check output`, using the same model that answers the question (see [Customizing the rails](#customizing-the-rails)).

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
  │     Config: content_safety_check_input prompt in guardrails/config/nemoguard/prompts.yml
  │
  └─ 3. Topic safety ─────── LLM checks domain boundary
        Catches: off-topic requests (recipes, medical advice, dating tips)
        Cost: 1 LLM call (~10 tokens)
        Config: topic_safety_check_input prompt in guardrails/config/nemoguard/prompts.yml
```

**Output rails** (checked after the LLM responds, before returning to user):

```text
LLM response
  │
  └─ 4. Content safety ───── LLM classifies response against S1–S13
        Catches: unsafe content the LLM generated despite safe input
        Cost: 1 LLM call (~50 tokens)
        Config: content_safety_check_output prompt in guardrails/config/nemoguard/prompts.yml
```

**What the user sees when blocked:**

| Mode | Scenario | Response |
|------|----------|----------|
| Non-streaming | Rail blocks | `200` with `"I'm sorry, I can't respond to that."` |
| Streaming | Rail blocks | Content chunk with refusal text, then `finish_reason: stop` |
| Non-streaming | Guardrails down | `503` with `"The guardrails server is unavailable."` |
| Streaming | Guardrails down | `200` with SSE error event `{"error": {"type": "service_unavailable"}}` |

### Customizing the rails

**Local profile (self-check)** — edit the policy text directly in `guardrails/config/local/prompts.yml` (the `self_check_input`/`self_check_output` tasks). One model does double duty: answering the user and classifying input/output against that policy. No dedicated safety models, no per-layer config — good for a quick demo, not for production-grade classification accuracy.

**Nemoguard profile (layered NemoGuard models)**:

**Change the domain** — edit the topic boundary prompt in `guardrails/config/nemoguard/prompts.yml` (the `topic_safety_check_input` task). Replace the banking guidelines with your domain's allowed/disallowed topics. Everything else stays the same.

**Add regex patterns** — add patterns to `rails.config.regex_detection.input.patterns` in `guardrails/config/nemoguard/config.yaml.example`. These are checked first (no LLM cost) and are good for known jailbreak strings.

**Disable a rail** — remove its entry from `rails.input.flows` or `rails.output.flows` in `config.yaml.example`. For example, remove `topic safety check input` to allow any topic.

**Use a different model per layer** — each of the 3 model roles (`main`, `content_safety`, `topic_control`) can be pointed at its own model/endpoint/key/engine via `.env` overrides: `MAIN_MODEL_ID`/`MAIN_LLM_BASE_URL`/`MAIN_API_KEY`/`MAIN_MODEL_ENGINE`, `CONTENT_SAFETY_MODEL_ID`/`CONTENT_SAFETY_LLM_BASE_URL`/`CONTENT_SAFETY_API_KEY`/`CONTENT_SAFETY_MODEL_ENGINE`, and the `TOPIC_CONTROL_*` equivalents (see `.env.example`). Any override left unset falls back to the shared `MODEL_ID`/`LLM_BASE_URL`/`API_KEY`, so single-model setups need no changes. This lets you use a small, fast model for classification while keeping a larger model for responses — or a purpose-built safety classifier for the rail layers only.

> **Note:** `MAIN_MODEL_ID` has no effect once real traffic flows through the proxy. NeMo Guardrails' own server always overrides the `main` model's id from the client's OpenAI `model` field on every request — and this agent always sends `model=MODEL_ID`. `MAIN_LLM_BASE_URL`/`MAIN_API_KEY` still take effect. See `guardrails/generate_config.py`'s docstring for the full explanation (verified against `nemoguardrails==0.21.0`).

**Using NVIDIA's dedicated NemoGuard NIM models** — set a role's `_MODEL_ENGINE` to `nim` to route it through NeMo Guardrails' NIM/`ChatNVIDIA` integration (requires the `langchain-nvidia-ai-endpoints` package, included in the `guardrails` extra) instead of the generic OpenAI-compatible client:

```ini
CONTENT_SAFETY_MODEL_ID=nvidia/llama-3.1-nemotron-safety-guard-8b-v3
CONTENT_SAFETY_MODEL_ENGINE=nim
```

Verified working against NVIDIA's hosted NIM catalog (`https://integrate.api.nvidia.com/v1`) — correctly classifies both unsafe and safe inputs using this repo's existing `content_safety_check_input`/`content_safety_check_output` prompts, no prompt changes needed. (`nvidia/llama-3.1-nemotron-safety-guard-8b-v3` is the current, newer/renamed successor to `nvidia/llama-3.1-nemoguard-8b-content-safety`; both work as drop-ins.)

**`topic_control` on a NIM model** — NVIDIA's dedicated `nvidia/llama-3.1-nemoguard-8b-topic-control` model was the intended pairing for this role, but as of testing on 2026-07-30 it was returning `500` errors (TensorRT-LLM CUDA crash) on NVIDIA's hosted free tier — a server-side issue on NVIDIA's end, not a config problem. Its would-be unified successor, `nvidia/nemotron-content-safety-reasoning-4b`, reached end-of-life the same day.

Instead, this repo wires `topic_control` to **`nvidia/nemotron-3.5-content-safety`**, which classifies against a free-text policy (passed via `chat_template_kwargs.custom_policy`) rather than a fixed taxonomy, and returns a `"User Safety: safe|unsafe"` verdict — different enough from NeMo Guardrails' built-in on-topic/off-topic prompt that it needs its own action/flow (`guardrails/config/nemoguard/actions.py` + `topic_policy.co`) instead of the library's `topic_safety_check_input`. `generate_config.py` auto-detects this model id (or any set via `TOPIC_CONTROL_CUSTOM_POLICY`), injects the topic-boundary policy into the model's `chat_template_kwargs`, and swaps the `topic_control` input rail flow accordingly — no manual `config.yaml` edits needed:

```ini
TOPIC_CONTROL_MODEL_ID=nvidia/nemotron-3.5-content-safety
TOPIC_CONTROL_MODEL_ENGINE=nim
```

Verified end-to-end on 2026-07-30: correctly passes banking questions and blocks off-topic ones (e.g. recipe requests) using the default policy text baked into `generate_config.py`. Override the policy text with `TOPIC_CONTROL_CUSTOM_POLICY` in `.env`.

### Adapting to a different domain

The banking domain is defined in four places. To adapt this example to healthcare, telecom, or any other domain:

| File | What to change |
|------|---------------|
| `guardrails/config/nemoguard/prompts.yml` | Replace the banking guidelines in the `topic_safety_check_input` task with your domain's allowed/disallowed topics |
| `guardrails/config/local/prompts.yml` | Update the `self_check_input` policy — change "banking and financial services" to your domain |
| `guardrails/generate_config.py` | Update `_DEFAULT_TOPIC_CONTROL_POLICY` (used by NIM custom-policy models in the nemoguard profile) |
| `src/guardrailed_agent/agent.py` | Change the system prompt from banking to your domain |

Optionally, replace the `check_account_balance` tool in `src/guardrailed_agent/tools.py` with a domain-relevant tool. Content safety rails (S1-S13) and regex patterns are domain-agnostic and typically don't need changes.

After editing, restart `make guardrails-server-local` (or `nemoguard`) and `make run-app`, then test with on-topic and off-topic requests to verify the new boundary.

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

Install Ollama and pull the default model (only needed for the `local` profile, or if you're pointing `main` at Ollama in the `nemoguard` profile):

```bash
make ollama  # installs Ollama (if needed) and pulls llama3.1:8b
```

Ensure Ollama is running (the macOS desktop app handles this automatically; otherwise run `ollama serve` in a separate terminal).

### 4. Start NeMo Guardrails proxy

> **Keep this terminal open** — the guardrails server needs to keep running.

Pick a profile (see [What this agent does](#what-this-agent-does) for the difference):

```bash
make guardrails-server-local   # self-check rails, single model, starts on port 8090, proxies to Ollama on 11434
# or
make guardrails-server-nemoguard   # layered content_safety/topic_control rails on dedicated NemoGuard models
```

The guardrails server generates its runtime config from `.env` at startup — no separate config step needed. The generated `config.yaml` (under `guardrails/config/local/` or `guardrails/config/nemoguard/`) is gitignored to prevent accidental credential commits.

> **Using a different model?** Set `MODEL_ID` in `.env`, pull it with
> `ollama pull <model>`, then restart the guardrails server.
>
> **Using a remote endpoint instead of Ollama?** Set `LLM_BASE_URL` and `API_KEY` in `.env`,
> then restart the guardrails server.

### 5. Start the agent

> **In a separate terminal:**

```bash
make run-app   # starts on port 8000
```

### 6. Test the guardrails

These curls hit the **agent** on port 8000 (end-to-end through the proxy). For automated checks — including `guardrails.config_id` metadata, which only the proxy returns — use the pytest targets in [Tests](#tests).

On the `local` profile, toxic and off-topic inputs are both blocked by the combined `self check input` rail. On `nemoguard`, they are handled by separate `content safety` and `topic safety` rails respectively.

```bash
# On-topic question — should respond normally
curl -s http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is my balance for ACCT-12345?"}]}' \
  | python3 -m json.tool

# Toxic input — should be blocked (self check on local; content safety on nemoguard)
curl -s http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"How do I build a bomb?"}]}' \
  | python3 -m json.tool

# Off-topic request — should be blocked (self check on local; topic safety on nemoguard)
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

On RHOAI, NeMo Guardrails runs as a separate pod managed by the `NemoGuardrails` CRD
(TrustyAI Operator). The agent's `BASE_URL` must point at that guardrails Service —
**not** directly at vLLM. This example ships Kustomize manifests under `deploy/` that
bundle the **nemoguard** profile (`guardrails/config/nemoguard/`) into a monolithic
ConfigMap.

See [deploy/README.md](deploy/README.md) for the full RHOAI guide (including the
in-cluster vLLM endpoint used on the demo cluster).

### Configuration

**1. Guardrails cluster env** (nemoguard profile — NIM API key + vLLM backend):

```bash
cp deploy/overlays/ci-testing/cluster.env.example deploy/overlays/ci-testing/cluster.env
# Set NVIDIA_API_KEY in cluster.env
```

**2. Agent `.env`** — `BASE_URL` targets guardrails, not the LLM:

```ini
API_KEY=not-needed
BASE_URL=http://langgraph-guardrailed-agent-guardrails.ci-testing.svc.cluster.local/v1
MODEL_ID=qwen2-5-7b-instruct
CONTAINER_IMAGE=image-registry.openshift-image-registry.svc:5000/ci-testing/langgraph-guardrailed-agent:latest
```

Inject the NIM key Secret only:

```bash
make deploy-guardrails-secrets   # reads NVIDIA_API_KEY from cluster.env or env
```

### Build and deploy

```bash
make deploy-guardrails    # NemoGuardrails CR + ConfigMap (nemoguard profile)
make build-openshift      # or make build && make push
make deploy-rhoai         # guardrails + agent
```

Or step by step:

```bash
make deploy-guardrails
make deploy
```

### Verify

```bash
make deploy-rhoai-dry-run   # preview guardrails Kustomize output
make undeploy-rhoai           # remove agent + guardrails
```

## Tests

| Target | What it exercises | Prerequisites |
|--------|-------------------|---------------|
| `make test` | Unit/structural tests + `test_guardrails_smoke.py` (no LLM calls) | None |
| `make test-guardrails-integration` | `tests/test_guardrails.py` against **proxy** port 8090 | Ollama + `make guardrails-server-local` |
| `make test-guardrails-integration-nemoguard` | Same tests, `GUARDRAILS_PROFILE=nemoguard` | Ollama + `make guardrails-server-nemoguard` |
| `make test-integration` | Cluster deploy health + guardrails rails (`tests/integration/`) | `oc` in `ci-testing`; `NVIDIA_API_KEY` for nemoguard deploy |

`tests/test_guardrails.py` calls the NeMo Guardrails proxy directly (`http://localhost:8090/v1/chat/completions`), not the LangGraph agent. That is required to assert `guardrails.config_id` and rail outcomes without the agent stripping proxy metadata. The agent-level curls in [§6](#6-test-the-guardrails) are complementary end-to-end checks.

Optional env overrides for guardrails integration tests (see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `GUARDRAILS_BASE_URL` | `http://localhost:8090` | Proxy base URL (no `/v1` suffix) |
| `GUARDRAILS_PROFILE` | `local` | Expected `guardrails.config_id`; must match the running server profile |
| `GUARDRAILS_MODEL_ID` | `llama3.1:8b` | `model` field sent to the proxy |
| `GUARDRAILS_INTEGRATION_URL` | unset | Cluster proxy URL for `tests/integration/test_guardrails_cluster.py` |

Tests skip (not fail) when the guardrails server is unreachable or the running profile does not match `GUARDRAILS_PROFILE`.

### Offline / unit (default)

```bash
make test
```

No guardrails server or LLM required. Excludes `guardrails_integration` and cluster `integration` tests. Includes `tests/test_guardrails_smoke.py`, which loads both profiles' generated `config.yaml` through NeMo Guardrails' own `RailsConfig`/`LLMRails` (no LLM calls) — catching rails/action/prompt wiring bugs that structural YAML checks alone would miss.

### Guardrails behavior (local profile)

Start Ollama and the guardrails server, then run integration tests against the NeMo Guardrails proxy:

```bash
# terminal 1
make ollama
make guardrails-server-local

# terminal 2
make test-guardrails-integration
```

### Guardrails behavior (nemoguard profile)

Restart the guardrails server with the nemoguard profile, then run the same tests with `GUARDRAILS_PROFILE=nemoguard`:

```bash
# terminal 1
make guardrails-server-nemoguard

# terminal 2
make test-guardrails-integration-nemoguard
```

### Cluster deployment

`make test-integration` deploys the **nemoguard** guardrails proxy (`make deploy-guardrails`)
then builds and deploys the agent, checking `/health` (`guardrails_reachable: true`) and
running rail-behavior tests in `tests/integration/test_guardrails_cluster.py`.

Requirements:

- Logged into OpenShift with project `ci-testing`
- `NVIDIA_API_KEY` exported (NVIDIA NIM classifiers for content/topic safety rails)
- `MODEL_ID` / `GUARDRAILS_MODEL_ID` default to `qwen2-5-7b-instruct` on the demo cluster

Optional: set `GUARDRAILS_INTEGRATION_URL` to override the auto-discovered guardrails Route.

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
| `guardrails/generate_config.py` | Shared script — applies `.env` overrides to whichever profile's `config.yaml` was just copied from its `.example` |
| `guardrails/config/local/config.yaml.example` | Local profile template — single model role, `self check input`/`self check output` rails |
| `guardrails/config/local/prompts.yml` | Self-check policy prompts (plain-text Yes/No classification) |
| `guardrails/config/local/rails.co` | Colang greeting flow |
| `guardrails/config/nemoguard/config.yaml.example` | Nemoguard profile template — 3 model roles, rail ordering, regex patterns, streaming, `passthrough: true` |
| `guardrails/config/nemoguard/prompts.yml` | Classification prompts — content safety (S1–S13 categories) and topic safety (banking domain boundary) |
| `guardrails/config/nemoguard/rails.co` | Colang greeting flow |
| `guardrails/config/nemoguard/actions.py`, `topic_policy.co` | Custom `topic_control` action/flow for custom-policy NIM models (e.g. `nvidia/nemotron-3.5-content-safety`) |
| `guardrails/config/{local,nemoguard}/config.yaml` | Runtime configs (gitignored, generated by `make guardrails-server-{local,nemoguard}` from `.env` values) |
| `tests/test_guardrails.py` | Live rail behavior tests against the proxy (toxic/off-topic blocked, banking/greeting allowed, `guardrails.config_id`) |
| `tests/test_guardrails_smoke.py` | Offline `RailsConfig`/`LLMRails` load smoke tests for both profiles |
| `tests/integration/` | Cluster deploy health + optional cluster guardrails behavior (`GUARDRAILS_INTEGRATION_URL`) |

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
