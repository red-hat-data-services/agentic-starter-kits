<div style="text-align: center;">

<img src="/images/a2a-logo-black.svg" alt="A2A (Agent-to-Agent) protocol logo" width="100" height="100">

# A2A: LangGraph ↔ CrewAI

*A2A logo from the upstream:* [`A2A project`](https://github.com/a2aproject/A2A/blob/main/docs/assets/a2a-logo-black.svg)

</div>

---

## What this agent does

An **A2A (Agent-to-Agent)** example: a **CrewAI** pod exposes an A2A JSON-RPC server, and a **LangGraph** pod acts as an orchestrator that calls the Crew specialist over HTTP/A2A inside the cluster (or locally). One container image is built from a single `Dockerfile`; **`A2A_ROLE`** in the pod (`crew` vs `langgraph`) selects which process runs.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) — for local container builds (`Makefile` uses whichever is on `PATH`)
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) — for OpenShift deployment
- [Helm](https://helm.sh/) — for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell — on Windows, use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended) or [Git Bash](https://git-scm.com/downloads)

---

## Local Development

### Setup

#### Initiating base

```bash
cd agents/a2a/templates/langgraph_crewai_agent
make init        # creates .env from template.env if missing
```

Edit `.env` with your configuration (see [Configuration](#configuration) below).

#### Creating environment

Install dependencies with `make env`, same idea as the Google ADK agent ([Creating environment](../../google/adk/README.md#creating-environment)):

```bash
make env
```

This runs `uv sync --python 3.12` and creates or updates `.venv`.

### Configuration

#### Pointing to a locally hosted model

You can use placeholders for container images if you only run Python locally:

```ini
API_KEY=your-key-or-not-needed
BASE_URL=http://localhost:8321/v1
MODEL_ID=ollama/Llama3.1:8B
CONTAINER_IMAGE=not-needed
CREW_A2A_PUBLIC_URL=http://127.0.0.1:9100
LANGGRAPH_A2A_PUBLIC_URL=http://127.0.0.1:9200
CREW_A2A_URL=http://127.0.0.1:9100
CREW_A2A_PORT=9100
LANGGRAPH_A2A_PORT=9200
```

See [Local Development](../../../docs/local-development.md) for Ollama + OGX setup for local model serving.

#### OpenShift cluster (values for `make build` / `make push` / `make deploy`)

Edit `.env` with your keys and registry image(s):

```ini
API_KEY=your-api-key-here
BASE_URL=https://your-ogx.example.com/v1
MODEL_ID=your-model-id
CONTAINER_IMAGE=quay.io/your-org/a2a-langgraph-crewai:latest
```

### Tracing with a local MLflow server (optional)

To enable MLflow tracing, add the following to your `.env`:

```ini
# Disable CrewAI's built-in tracing (we use MLflow instead)
CREWAI_TRACING_ENABLED=false

MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="a2a-langgraph-crewai"
MLFLOW_HTTP_REQUEST_TIMEOUT=2
MLFLOW_HTTP_REQUEST_MAX_RETRIES=0
```

**Important:** `CREWAI_TRACING_ENABLED=false` disables CrewAI's built-in telemetry system, which can interfere with execution and block the crew from running. We use MLflow for tracing instead.

Then start the MLflow server in a separate terminal:

```bash
# Start the MLflow server
uv run --extra tracing mlflow server --port 5000
```

When `MLFLOW_TRACKING_URI` is set, `make run-app`, `make run-crew`, and `make run-langgraph` will automatically install the tracing dependency.

#### Configuring the LLM provider for tracing (CrewAI only)

The CrewAI server can use different LLM providers. Set `LLM_PROVIDER` to match your provider so MLflow uses the correct autolog integration:

| `LLM_PROVIDER` value | MLflow autolog enabled       | When to use                 |
|----------------------|------------------------------|-----------------------------|
| `litellm` (default)  | `mlflow.litellm.autolog()`   | OpenAI-compatible endpoints |
| `openai`             | `mlflow.openai.autolog()`    | Direct OpenAI API           |
| `anthropic`          | `mlflow.anthropic.autolog()` | Anthropic API               |
| `gemini`             | `mlflow.gemini.autolog()`    | Google Gemini API           |
| `azure`              | `mlflow.openai.autolog()`    | Azure OpenAI                |
| `bedrock`            | `mlflow.bedrock.autolog()`   | AWS Bedrock                 |

**Note:** The LangGraph server uses `mlflow.langchain.autolog()` which automatically traces LangChain components regardless of the underlying LLM provider, so `LLM_PROVIDER` only affects the CrewAI server.

### Tracing with an OpenShift MLflow server (optional)

To enable tracing and logging with MLflow on your OpenShift cluster, add the following environment variables to your `.env` file:

```ini
# Disable CrewAI's built-in tracing (we use MLflow instead)
CREWAI_TRACING_ENABLED=false

MLFLOW_TRACKING_URI="https://<openshift-dashboard-url>/mlflow"
MLFLOW_TRACKING_TOKEN="<your-openshift-token>"
MLFLOW_EXPERIMENT_NAME="a2a-langgraph-crewai"
MLFLOW_TRACKING_INSECURE_TLS="true"  # ⚠️ Development only - use proper certificates in production
MLFLOW_WORKSPACE="default"
```

**Notes:**

- `MLFLOW_TRACKING_URI` - Replace `<openshift-dashboard-url>` with your OpenShift cluster's data science gateway URL
- `MLFLOW_TRACKING_TOKEN` - Your openshift authentication token. It can be obtained from the openshift console.
- `MLFLOW_EXPERIMENT_NAME` - A descriptive name for your experiment (e.g., "A2A LangGraph CrewAI Demo")
- `MLFLOW_TRACKING_INSECURE_TLS` - **Development only** - disables certificate verification. Never use in production. Deploy proper TLS certificates instead.
- `MLFLOW_WORKSPACE` - Project name
- `LLM_PROVIDER` - (CrewAI only) Which provider autolog to use (default: `litellm`)

- Tracing is optional; if you do not set `MLFLOW_TRACKING_URI`, the application will run without MLflow logging.
- If `MLFLOW_TRACKING_URI` is set, the application will attempt to connect to the MLflow server at startup. If the server is unreachable, the application will log a warning and continue running without tracing.
- Both servers (CrewAI and LangGraph) will emit traces to the same MLflow experiment when tracing is enabled.

#### Differentiating traces from each server

By default, both servers emit traces to the same experiment. You can differentiate traces using:

**1. Span names (automatic)** - Each framework produces distinct span names:

- LangGraph traces: `LangGraph`, `ChatOpenAI`, `ask_crew_specialist`
- CrewAI traces: `CrewAI`, `Task`, `Agent`, `Web Search`

**2. Separate experiments (optional)** - Use different experiments for each server:

```ini
# Separate experiments
MLFLOW_EXPERIMENT_NAME_LANGGRAPH="a2a-langgraph-traces"
MLFLOW_EXPERIMENT_NAME_CREWAI="a2a-crewai-traces"

# Shared experiment (default if above not set)
MLFLOW_EXPERIMENT_NAME="a2a-langgraph-crewai"
```

If `MLFLOW_EXPERIMENT_NAME_LANGGRAPH` or `MLFLOW_EXPERIMENT_NAME_CREWAI` are set, they take priority over `MLFLOW_EXPERIMENT_NAME` for their respective servers.

### Running the agent

Install dependencies and configure `.env`, then either use **Make** (same idea as the Google ADK agent) or run the two Python modules by hand.

**Option A — one terminal (`make run-app`)**

```bash
make init         # .env from template.env if needed — then edit .env
make env          # uv sync into .venv (once)
make run-app      # Crew in background, LangGraph in foreground (Ctrl+C stops both)
```

If ports **9100** / **9200** are stuck: `make run-app-fresh`.

**Option B — two terminals (`uv run`)**

```bash
uv sync
set -a && source .env && set +a
```

```bash
# Terminal 1 — CrewAI + A2A
uv run python -m a2a_langgraph_crewai.crew_a2a_server

# Terminal 2 — LangGraph orchestrator
uv run python -m a2a_langgraph_crewai.langgraph_a2a_server
```

Single-process shortcuts: `make run-crew` or `make run-langgraph`.

Default ports: **9100** (Crew), **9200** (LangGraph). Do not set `PORT` unless you mirror the container (`8080`).

### Playground (LangGraph orchestrator)

With the LangGraph server running (terminal 2), open **<http://127.0.0.1:9200/>** in a browser. The chat uses **A2A JSON-RPC** on **`POST /`** with **`message/send`**. The server also exposes **`POST /chat/completions`** (OpenAI-style). For local `curl`, use `http://127.0.0.1:9200`.

---

## Deploying to OpenShift

Uses **[Helm](https://helm.sh/)** + **`Makefile`**. Chart: **`agents/a2a/deployment/`** (two Deployments, two Services, two Routes, one Secret).

### Setup

```bash
cd agents/a2a/templates/langgraph_crewai_agent
make init
```

### Configuration

Edit `.env` with your model endpoint and container image(s).

**Option A — one registry path; `make build` / `make push` produce `:crew` and `:langgraph` from the same stem:**

```ini
API_KEY=your-api-key-here
BASE_URL=https://your-model-endpoint.com/v1
MODEL_ID=your-model-id
CONTAINER_IMAGE=quay.io/your-username/a2a-langgraph-crewai:latest
```

**Option B — two full image refs (e.g. separate repos or explicit tags):**

```ini
API_KEY=your-api-key-here
BASE_URL=https://your-model-endpoint.com/v1
MODEL_ID=your-model-id
CONTAINER_IMAGE_CREW=quay.io/your-username/a2a-crewai:latest
CONTAINER_IMAGE_LANGGRAPH=quay.io/your-username/a2a-langgraph:latest
```

**Notes:**

- `API_KEY` — your API key or contact your cluster administrator
- `BASE_URL` — should end with `/v1`
- `MODEL_ID` — model identifier available on your endpoint
- **`CONTAINER_IMAGE_CREW`** and **`CONTAINER_IMAGE_LANGGRAPH`** instead.

  Examples (stem style): Quay.io `quay.io/your-username/a2a-langgraph-crewai:latest`, Docker Hub, GHCR — same pattern as `template.env`.

  > **Note:** OpenShift must be able to pull **both** image refs. Make them **public**, or configure an [image pull secret](https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html) for private registries.

### Building the container image

Log in to the cluster and registry:

```bash
oc login --token=<token> --server=https://<cluster-api-url>
oc project <namespace>
docker login -u='login' -p='password' quay.io
```

#### Option A: Build locally and push to a registry

Requires Podman or Docker (with `buildx` where needed) and a registry account (e.g. Quay.io).

`make build` loads the image locally and tags **`:crew`** and **`:langgraph`** (one build, second ref via `tag`). `make push` uploads both refs to the registry.

```bash
make build    # build once, tag :crew and :langgraph locally
make push     # push both tags to the registry
```

Run **`make build && make push`** after image or `Dockerfile` changes, then **`make deploy`**.

### Deploying

#### Preview manifests (`make dry-run`)

```bash
make dry-run          # preview rendered Helm manifests (secrets redacted)
```

#### Deploy (`make deploy`)

```bash
make deploy
```

The LangGraph pod uses in-cluster **`CREW_A2A_URL=http://a2a-crew-agent:8080`**.

#### Manage Agents using Kagenti (Optional)

Register agents with [Kagenti](https://github.com/kagenti/kagenti) for unified discovery and management.

**Prerequisites:**

- Kagenti installed: `oc get pods -n kagenti-system`
- Namespace labeled: `oc label namespace <your-namespace> kagenti-enabled=true`

**Apply AgentRuntime:**

NOTE: The `AgentRuntime.yaml` file will be applied
Apply:

   ```bash
   oc apply -f AgentRuntime.yaml
   ```

**Verify:**

```bash
oc get agentcard -n <your-namespace>
```

AgentCards for both LangGraph and CrewAI will appear in Kagenti UI.

#### Verify deployment

After deploying, the application may take about a minute to become available while the pods start.

Route hosts are printed after `make deploy`. Retrieve them manually:

```bash
oc get route a2a-langgraph-agent -o jsonpath='{.spec.host}'
```

#### Remove deployment (`make undeploy`)

```bash
make undeploy
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for more details.

---

## API Endpoints (LangGraph route)

**Use the LangGraph orchestrator for every `curl` below** — Route **`a2a-langgraph-agent`** on OpenShift, or **`http://127.0.0.1:9200`** locally. That is the public entrypoint (playground, Agent Card, `/health`, A2A JSON-RPC, `/chat/completions`).

Do **not** aim `curl` at the Crew specialist (`a2a-crew-agent` / port **9100**): Crew is the peer the LangGraph pod calls over A2A in-cluster; clients should talk to **LangGraph** so the orchestrator can delegate when needed.

On OpenShift, routes terminate TLS at the edge; use **`https://`**. Replace **`<YOUR_ROUTE_URL>`** with the **LangGraph** route host, e.g.:

```bash
oc get route a2a-langgraph-agent -o jsonpath='{.spec.host}'
```

### GET `/.well-known/agent-card.json`

```bash
curl -sS "https://<YOUR_ROUTE_URL>/.well-known/agent-card.json"
```

### GET `/health`

```bash
curl -sS "http://127.0.0.1:9200/health"
```

```bash
curl -sS "https://<YOUR_ROUTE_URL>/health"
```

### POST `/` — A2A JSON-RPC (`message/send`)

Same protocol as the browser playground: JSON-RPC 2.0 body = `SendMessageRequest` (see [a2a-sdk](https://pypi.org/project/a2a-sdk/)). Use a unique `messageId` per request.

```bash
curl -sS -X POST "https://<YOUR_ROUTE_URL>/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"Use the web search tool to find the Red Hat encrypted string."}],"messageId":"0123456789abcdef0123456789abcdef"}},"id":"curl-req-1"}'
```

The response is JSON-RPC (`result` or `error`), not OpenAI chat format.

### POST `/chat/completions`

Non-streaming:

```bash
curl -sS -X POST "https://<YOUR_ROUTE_URL>/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Use the web search tool to find the Red Hat encrypted string."}],"stream":false}'
```

Streaming (SSE; use `-N` / `--no-buffer` so chunks print as they arrive):

```bash
curl -sS -N -X POST "https://<YOUR_ROUTE_URL>/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"messages":[{"role":"user","content":"Use the web search tool to find the Red Hat encrypted string."}],"stream":true}'
```

For local runs, use `http://127.0.0.1:9200` instead of `https://<YOUR_ROUTE_URL>`. The stream may include leading `a2a.protocol` trace events before `chat.completion.chunk` lines.

---

## Agent-specific documentation

### Architecture (OpenShift)

| Resource | Role |
|----------|------|
| Helm chart **`agents/a2a/deployment`** | Secret, Services, Routes, Deployments |
| `Deployment` **a2a-crew-agent** | CrewAI + A2A server, port **8080** |
| `Deployment` **a2a-langgraph-agent** | LangGraph + tool → `CREW_A2A_URL` |
| `Service` + `Route` ×2 | HTTPS; hosts feed Agent Card URLs |
| In-cluster | `CREW_A2A_URL=http://a2a-crew-agent:8080` |

## Testing

### Unit tests

```bash
make test
```

### Behavioral tests

Behavioral tests validate tool selection, response quality, latency, and reliability of the LangGraph orchestrator via its `/chat/completions` endpoint.

```bash
# Set the agent URL (LangGraph server)
export A2A_LANGGRAPH_CREWAI_AGENT_URL="https://<langgraph-route>"

# Optional: enable MLflow trace enrichment for tool_calls extraction
export MLFLOW_TRACKING_URI="https://<mlflow-route>"
export MLFLOW_EXPERIMENT_NAME="<mlflow-experiment-name>"

# Run behavioral tests
pytest agents/a2a/templates/langgraph_crewai_agent/tests/behavioral/ -m a2a_langgraph_crewai -v
```

**Note:** This is a multi-pod agent. Behavioral tests target the **LangGraph server** (`a2a-langgraph-agent`), which delegates to the CrewAI specialist (`a2a-crew-agent`) via the A2A protocol. Both pods must be running for tool-delegation tests to pass.

---

## Resources

- [A2A Python SDK](https://pypi.org/project/a2a-sdk/)
- [Deploying to OpenShift (generic)](../../../docs/openshift-deployment.md)
- [Local Development](../../../docs/local-development.md)
- Related patterns: `agents/google/templates/adk/` (Helm + `make build` / `make push` / `make deploy`), `agents/llamaindex/templates/websearch_agent/`, `agents/langgraph/templates/react_agent/`
