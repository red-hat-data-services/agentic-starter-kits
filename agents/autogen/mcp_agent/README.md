<div style="text-align: center;">

![AutoGen Logo](/images/autogen_logo.svg)

# AutoGen Agent (MCP)

</div>

---

## What this agent does

An AutoGen-based agent with MCP (Model Context Protocol) tools over SSE. It connects to an MCP server, loads tools
dynamically (e.g. churn prediction, deployment), and answers user questions via an OpenAI-compatible
`POST /chat/completions` API. Built with AutoGen `AssistantAgent` and `autogen_ext.tools.mcp`.

**Key features:**

- Discovers and loads tools from an MCP server at startup
- Uses `reflect_on_tool_use=True` so the LLM reasons about tool results before responding
- Supports both streaming (SSE) and non-streaming responses (streaming auto-adjusts when MLflow tracing is enabled; see [Tracing](#tracing) section)
- Includes an interactive web playground with an MCP tools panel
- Extends OpenAI streaming with `mcp.tool_usage` events and `tool_invocations` in JSON responses

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) — for local container builds (Option A)
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) — for OpenShift deployment
- [Helm](https://helm.sh/) — for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell — on Windows, use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended) or [Git Bash](https://git-scm.com/downloads)
- **MCP Server** — this agent requires a running MCP server (included in `mcp_automl_template/`)

## Deploying Locally

### Setup

```bash
cd agents/autogen/mcp_agent
make init        # creates .env from .env.example
```

### Install dependencies

```bash
make env
```

### Configure your model

Edit `.env` to point the agent at an LLM. Choose **one** of the two options below.

#### Option A: Local model (Ollama + Llama Stack)

Set the following in `.env`:

```ini
API_KEY=not-needed
BASE_URL=http://localhost:11434/v1
MODEL_ID=llama3.1:8b
```

Then install Ollama and pull the model:

```bash
make ollama                    # default model: llama3.1:8b
make ollama MODEL=llama3.2:3b  # or specify a different model
```

Start the Llama Stack server (keep this terminal open):

```bash
make llama-server
```

> You should see output indicating the server started on `http://localhost:8321`.

#### Option B: Remote model

Set the following in `.env`:

```ini
API_KEY=your-api-key-here
BASE_URL=https://your-model-endpoint.com/v1
MODEL_ID=llama-3.1-8b-instruct
```

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint

### MCP Configuration

The agent can connect to any MCP server that supports SSE transport. By default it points to the bundled `mcp_automl_template` server(no configuration needed):

| Environment | Default `MCP_SERVER_URL` | How it's set |
|-------------|--------------------------|--------------|
| Local (`make run-app`) | `http://127.0.0.1:8080/sse` | Makefile fallback |
| OpenShift (`make deploy`) | `http://mcp-automl:8080/sse` | `values.yaml` (in-cluster service DNS) |

To connect to an external MCP server, set `MCP_SERVER_URL` in your `.env`:

```ini
MCP_SERVER_URL=https://your-external-mcp-server.example.com/sse
```

#### DNS Rebinding Protection

MCP SDK ≥1.x enables host-header DNS rebinding protection by default. When running the MCP server behind an
OpenShift Route (or any reverse proxy that rewrites the `Host` header), the MCP server may reject requests.
To disable this protection, uncomment and set in your `.env`:

```ini
DISABLE_DNS_REBINDING_PROTECTION=true
```

This is passed to the MCP server deployment (`make deploy-mcp`). Leave it commented out (protection enabled)
unless you encounter host-header mismatch errors.

#### MCP AutoML Server Variables

If you plan to deploy the MCP AutoML server to OpenShift (`make deploy-mcp`) with tools that call an ML model serving endpoint (e.g. churn prediction via KServe/AutoML), set these in your `.env`:

```ini
DEPLOYMENT_URL=https://your-model-serving-endpoint.com/v1/models/your-model:predict
DEPLOYMENT_TOKEN=your-model-serving-bearer-token
```

- `DEPLOYMENT_URL` — URL of the ML model serving endpoint called by MCP tools at runtime
- `DEPLOYMENT_TOKEN` — Bearer token for authenticating with the model serving endpoint

### Tracing (optional)

Tracing is optional. If MLflow tracing is required, enable it by uncommenting and setting the following environment variables in the `.env` file.

#### Tracing with a local MLflow server

```ini
MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="autogen-mcp-agent"
MLFLOW_HTTP_REQUEST_TIMEOUT=2
MLFLOW_HTTP_REQUEST_MAX_RETRIES=0
```

Then start the MLflow server in a separate terminal:

```bash
# Start the MLflow server
uv run --extra tracing mlflow server --port 5000
```

When `MLFLOW_TRACKING_URI` is set, `make run-app` will automatically install the tracing dependency.

#### Tracing with an OpenShift MLflow server

To enable tracing and logging with MLflow on your OpenShift cluster, add the following environment variables to your `.env` file:

```ini
MLFLOW_TRACKING_URI="https://<openshift-dashboard-url>/mlflow"
MLFLOW_TRACKING_TOKEN="<your-openshift-token>"
MLFLOW_EXPERIMENT_NAME="autogen-mcp-agent"
MLFLOW_TRACKING_INSECURE_TLS="true"
MLFLOW_WORKSPACE="default"
```

**Notes:**
- `MLFLOW_TRACKING_URI` - URL of your MLflow server. For local development, use `http://localhost:5000`. If using MLflow on an OpenShift cluster, replace `<openshift-dashboard-url>` with your cluster's data science gateway URL.
- `MLFLOW_TRACKING_TOKEN` - Required for OpenShift only. Your OpenShift authentication token, obtained from the OpenShift console.
- `MLFLOW_EXPERIMENT_NAME` - A descriptive name for your experiment (e.g., "AutoGen MCP Demo")
- `MLFLOW_TRACKING_INSECURE_TLS` - Required for OpenShift only. Set to `"true"` if your cluster does not use trusted certificates.
- `MLFLOW_WORKSPACE` - Required for OpenShift only. Project name.

- Tracing is optional; if you do not set `MLFLOW_TRACKING_URI`, the application will run without MLflow logging.

- If `MLFLOW_TRACKING_URI` is set, the application will attempt to connect to the MLflow server at startup. If the server is unreachable, the application will log a warning and continue running without tracing.

- You can control how long the application waits for the MLflow server by setting `MLFLOW_HEALTH_CHECK_TIMEOUT` (in seconds, default: `5`).

#### Streaming and tracing

`mlflow.autogen.autolog()` does not support AutoGen's streaming APIs (`run_stream`, `create_stream`) as of now. To handle this, streaming is **auto-detected**:

- When `MLFLOW_TRACKING_URI` is **not set** → streaming is enabled (playground works)
- When `MLFLOW_TRACKING_URI` is **set** → streaming is disabled (complete MLflow traces)

You can always override this by setting `MODEL_CLIENT_STREAM` explicitly in your `.env`:

```ini
MODEL_CLIENT_STREAM=true   # force streaming on (playground works, traces incomplete)
MODEL_CLIENT_STREAM=false  # force streaming off (complete traces, playground won't display responses)
```

When streaming is enabled, traces will be incomplete — LLM spans will be missing and remaining spans (TOOL) will be orphaned without a parent AGENT span. Once MLflow adds native support for AutoGen streaming, traces will work automatically without any code changes.

### Running the Agent

This agent requires **two terminals** — one for the MCP server and one for the agent itself.

#### Terminal 1 — Start MCP server

The MCP server must be running before the agent starts:

```bash
make run-mcp
```

This starts the MCP AutoML server on port 8080.

#### Terminal 2 — Start agent

```bash
make run-app           # fails if port is already in use
make run-app-fresh     # kills existing process on port, then starts
```

The agent starts on port 8000. Open [http://localhost:8000](http://localhost:8000) in your browser. A green dot in
the header means the agent is connected and ready.

The playground includes an **MCP tools** panel that shows which tools were invoked for the last reply, along with
their arguments and results. You can also open [http://localhost:8000/docs](http://localhost:8000/docs) for the
Swagger UI to explore and test the API interactively.

#### Quick test

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2+7? Use a tool!"}'
```

#### Interactive MCP chat (optional)

You can also interact with the MCP tools directly via a LangGraph agent (bypasses the AutoGen agent):

```bash
make interact-mcp
```

## Deploying to OpenShift

> **Before you begin:** Log in to OpenShift (`oc login`) and, if using local build + push, your container registry (`podman login`).
> See [OpenShift Deployment](../../../docs/openshift-deployment.md) for full prerequisites and step-by-step instructions.

### Step 1: Deploy the MCP server

The MCP AutoML server must be deployed before the agent. Make sure `DEPLOYMENT_URL` and
`DEPLOYMENT_TOKEN` are set in your `.env`, then run:

```bash
make deploy-mcp
```

This builds the MCP server image in-cluster via OpenShift BuildConfig and deploys it using the shared Helm chart. The Route URL is printed on success. See `mcp_automl_template/README.md` for details.

### Step 2: Build the agent container image

#### Option A: Build locally and push to a registry

Requires Podman (or Docker) and a registry account (e.g., Quay.io).

```bash
make build    # builds the image locally
make push     # pushes to the registry specified in CONTAINER_IMAGE
```

#### Option B: Build in-cluster via OpenShift BuildConfig

No Podman, Docker, or registry account needed — just the `oc` CLI.

```bash
make build-openshift
```

After the build completes, set `CONTAINER_IMAGE` in your `.env` to the internal registry URL printed after the build.

### Step 3: Deploy the agent

Edit `.env` with your model endpoint and container image:

```ini
API_KEY=your-api-key-here
BASE_URL=https://your-model-endpoint.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/autogen-mcp-agent:latest
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/autogen-mcp-agent:latest`
    - Docker Hub: `docker.io/your-username/autogen-mcp-agent:latest`
    - GHCR: `ghcr.io/your-org/autogen-mcp-agent:latest`

#### Preview manifests

```bash
make dry-run          # preview agent Helm manifests (secrets redacted)
make dry-run-mcp      # preview MCP server Helm manifests
```

#### Deploy (`make deploy`)

```bash
make deploy
```

The agent's `MCP_SERVER_URL` defaults to `http://mcp-automl:8080/sse` (in-cluster DNS), so it will automatically
connect to the MCP server deployed in Step 1.

#### Verify deployment

After deploying, the application may take about a minute to become available while the pod starts up.

The route URL is printed after `make deploy`. You can also retrieve it manually:

```bash
oc get route autogen-mcp-agent -o jsonpath='{.spec.host}'
```

#### Remove deployment (`make undeploy`)

```bash
make undeploy
```

> **Note:** `make undeploy` removes only the agent. To also remove the MCP server:
> ```bash
> make undeploy-mcp
> ```

## API Endpoints

### POST /chat/completions

You can use either `"message": "..."` (shortcut) or `"messages": [...]` (OpenAI format).

#### Non-streaming

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 17 + 25? Use your tools to compute it."}'
```

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Predict churn for this customer: Male, 12 months tenure, fiber optic, month-to-month contract, electronic check, monthly 70.35, total 800.40."}], "stream": false}'
```

Non-streaming responses include a `tool_invocations` array with each tool's `name`, `arguments`, `result`, and
`is_error` status.

#### Streaming

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is 2+2? Use a tool if needed."}], "stream": true}'
```

Streaming responses follow the OpenAI SSE format (`chat.completion.chunk` events). If MCP tools were used, an extra
SSE event with `"object": "mcp.tool_usage"` is sent before `[DONE]`:

```json
data: {"object": "mcp.tool_usage", "tools": [{"name": "invoke_churn", "arguments": {...}, "result": "...", "is_error": false}]}
```

This is an extension to the OpenAI streaming protocol — clients can safely ignore it.

#### Pretty Printed Stream

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is 17 + 25? Use your tools."}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

### GET /health

```bash
curl http://localhost:8000/health
```

Returns `200` with `"status": "healthy"` when the MCP-backed agent is ready; `503` with `"status": "not_ready"`
until initialization completes.

---

## Architecture

This agent is built on:

- **AutoGen `AssistantAgent`** — reasoning and tool selection via an LLM (OpenAI-compatible API)
- **MCP SSE transport** (`autogen_ext.tools.mcp`) — connects to an MCP server over Server-Sent Events
- **Tool discovery** — tools are loaded dynamically from the MCP server at startup (e.g. `invoke_churn`, `add`, `multiply`)
- **`reflect_on_tool_use=True`** — the LLM reviews tool results and formulates a final answer
- **FastAPI** — serves the `/chat/completions` endpoint with both streaming and non-streaming modes

---

## MCP AutoML Server

The MCP AutoML server (`mcp_automl_template/`) provides the tools that this agent uses. It exposes machine learning
tools (e.g. churn prediction) via the Model Context Protocol over SSE.

See [`mcp_automl_template/README.md`](mcp_automl_template/README.md) for setup, tool configuration, and deployment
instructions.

---

## Documentation and references

- [AutoGen](https://microsoft.github.io/autogen/)
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)
- [Llama Stack Documentation](https://llama-stack.readthedocs.io/)
- MCP server in this repo: `mcp_automl_template/` (README, tool configuration, deploy)
