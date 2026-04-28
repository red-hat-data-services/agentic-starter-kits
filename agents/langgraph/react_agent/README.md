<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# ReACT Agent

</div>

---

## What this agent does

General-purpose agent using a ReAct loop: it reasons and calls tools (e.g. search, math) step by step. Built with
LangGraph and LangChain.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) — for local container builds (Option A)
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) — for
  OpenShift deployment
- [Helm](https://helm.sh/) — for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell — on Windows,
  use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended)
  or [Git Bash](https://git-scm.com/downloads)

## Local Development

#### Initiating base

`make init` creates a `.env` file from `.env.example`. Set your environment variables in the `.env` file.

```bash
cd agents/langgraph/react_agent
make init
```

#### Tracing (optional)

Tracing is optional. If MLflow tracing is required, enable it by uncommenting and setting the following environment variables in the `.env` file.

##### Tracing with a local MLflow server

```ini
MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="langgraph-react-agent"
MLFLOW_HTTP_REQUEST_TIMEOUT=2
MLFLOW_HTTP_REQUEST_MAX_RETRIES=0
```

Then start the MLflow server in a separate terminal:

```bash
# Start the MLflow server
uv run --extra tracing mlflow server --port 5000
```

When `MLFLOW_TRACKING_URI` is set, `make run-app` and `make run-cli` will automatically install the tracing dependency.

##### Tracing with an OpenShift MLflow server

To enable tracing and logging with MLflow on your OpenShift cluster, add the following environment variables to your `.env` file:

```ini
MLFLOW_TRACKING_URI="https://<openshift-dashboard-url>/mlflow"
MLFLOW_TRACKING_TOKEN="<your-openshift-token>"
MLFLOW_EXPERIMENT_NAME="langgraph-react-agent"
MLFLOW_TRACKING_INSECURE_TLS="true"
MLFLOW_WORKSPACE="default"
```

**Notes:**
- `MLFLOW_TRACKING_URI` - URL of your MLflow server. For local development, use `http://localhost:5000`. If using MLflow on an OpenShift cluster, replace `<openshift-dashboard-url>` with your cluster's data science gateway URL.
- `MLFLOW_TRACKING_TOKEN` - Required for OpenShift only. Your OpenShift authentication token, obtained from the OpenShift console.
- `MLFLOW_EXPERIMENT_NAME` - A descriptive name for your experiment (e.g., "LangGraph ReAct Demo")
- `MLFLOW_TRACKING_INSECURE_TLS` - Required for OpenShift only. Set to `"true"` if your cluster does not use trusted certificates.
- `MLFLOW_WORKSPACE` - Required for OpenShift only. Project name.

- Tracing is optional; if you do not set `MLFLOW_TRACKING_URI`, the application will run without MLflow logging.

- If `MLFLOW_TRACKING_URI` is set, the application will attempt to connect to the MLflow server at startup. If the server is unreachable, the application will log a warning and continue running without tracing.

- You can control how long the application waits for the MLflow server by setting `MLFLOW_HEALTH_CHECK_TIMEOUT` (in seconds, default: `5`).

#### Creating environment

Now you will remove old .venv and create new. Next dependencies will be installed.

```bash
make env
```

#### Setup Ollama

This will install ollama if it is not installed already. Then pull needed models for local work.
The default model is `llama3.1:8b`. To use a different model, pass `MODEL=`:
`make ollama MODEL=llama3.2:3b`

```bash
make ollama
```

#### Run llama server

> **Keep this terminal open** – the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.

```bash
make llama-server
```

#### Run the interactive web application

> **Keep this terminal open** – the app needs to keep running.
> You should see output indicating the app started on `http://localhost:8000`.

```bash
cd agents/langgraph/react_agent
make run-app           # fails if port is already in use and print steps TO-DO
```

#### Interactive CLI

For terminal-based testing without a browser:

```bash
cd agents/langgraph/react_agent
make run-cli
```

This launches an interactive prompt where you can pick predefined questions or type your own. Tool calls and results are
displayed inline with colored output.

## Deploying to OpenShift

### Setup

```bash
cd agents/langgraph/react_agent
make init
```

### Configuration

Edit `.env` with your model endpoint and container image:

```ini
API_KEY = your-api-key-here
BASE_URL = https://your-model-endpoint.com/v1
MODEL_ID = llama-3.1-8b-instruct
CONTAINER_IMAGE = quay.io/your-username/langgraph-react-agent:latest
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/langgraph-react-agent:latest`
    - Docker Hub: `docker.io/your-username/langgraph-react-agent:latest`
    - GHCR: `ghcr.io/your-org/langgraph-react-agent:latest`

  > **Note:** OpenShift must be able to pull the container image. Make the image **public**, or configure
  an [image pull secret](https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html)
  for private registries.

### Building the Container Image

Login to OC

```bash
oc login -u "login" -p "password" https://super-link-to-cluster:111
```

Login ex. Docker

```bash
docker login -u='login' -p='password' quay.io
```

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

### Deploying

#### Preview manifests (`make dry-run`)

```bash
make dry-run          # preview rendered Helm manifests (secrets redacted)
```

#### Deploy (`make deploy`)

```bash
make deploy
```

#### Verify deployment

After deploying, the application may take about a minute to become available while the pod starts up.

The route URL is printed after `make deploy`. You can also retrieve it manually:

```bash
oc get route langgraph-react-agent -o jsonpath='{.spec.host}'
```

#### Remove deployment (`make undeploy`)

```bash
make undeploy
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for more details.

## Tests

```bash
make test
```

## API Endpoints

### POST /chat/completions

Non-streaming:

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is the best cluster hosting service?"}], "stream": false}'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is the best cluster hosting service?"}], "stream": true}'
```

Pretty Printed Stream:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is the best cluster hosting service?"}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

### GET /health

```bash
curl http://localhost:8000/health
```

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Documentation](https://python.langchain.com/)
- [Llama Stack Documentation](https://llama-stack.readthedocs.io/)
- [Ollama Documentation](https://ollama.com/docs)
