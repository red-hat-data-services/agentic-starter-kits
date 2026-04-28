<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# ReACT Agent with Database Memory

</div>

---

## What this agent does

ReAct agent with PostgreSQL-based conversation memory. It reasons and calls tools step by step (like the base ReAct
agent), but stores all conversation history in a PostgreSQL database using thread IDs so conversations persist across
sessions. Built with LangGraph, LangChain, and `langgraph-checkpoint-postgres`.

Key features:

- **Thread-based persistence** -- each conversation is identified by a unique `thread_id`
- **FIFO message trimming** -- only the most recent messages (default: 5) are sent to the LLM, keeping context windows
  manageable
- **Auto-managed schema** -- PostgreSQL tables are created automatically on first run via LangGraph's `PostgresSaver`
  checkpointer

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) -- Python package manager
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) -- for local container builds (Option A)
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) -- for
  OpenShift deployment
- [Helm](https://helm.sh/) -- for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell -- on Windows,
  use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended)
  or [Git Bash](https://git-scm.com/downloads)
- **PostgreSQL 14+** -- managed service or local instance (see setup below)

## Local Development

#### Initiating base

`make init` creates a `.env` file from `.env.example`. Set your environment variables in the `.env` file.

```bash
cd agents/langgraph/react_with_database_memory
make init
```

#### Tracing (optional)

Tracing is optional. If MLflow tracing is required, enable it by uncommenting and setting the following environment variables in the `.env` file.

##### Tracing with a local MLflow server

```ini
MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="langgraph-db-memory-agent"
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
MLFLOW_EXPERIMENT_NAME="langgraph-db-memory-agent"
MLFLOW_TRACKING_INSECURE_TLS="true"
MLFLOW_WORKSPACE="default"
```

**Notes:**
- `MLFLOW_TRACKING_URI` - URL of your MLflow server. For local development, use `http://localhost:5000`. If using MLflow on an OpenShift cluster, replace `<openshift-dashboard-url>` with your cluster's data science gateway URL.
- `MLFLOW_TRACKING_TOKEN` - Required for OpenShift only. Your OpenShift authentication token, obtained from the OpenShift console.
- `MLFLOW_EXPERIMENT_NAME` - A descriptive name for your experiment (e.g., "LangGraph DB Memory Demo")
- `MLFLOW_TRACKING_INSECURE_TLS` - Required for OpenShift only. Set to `"true"` if your cluster does not use trusted certificates.
- `MLFLOW_WORKSPACE` - Required for OpenShift only. Project name.

- Tracing is optional; if you do not set `MLFLOW_TRACKING_URI`, the application will run without MLflow logging.

- If `MLFLOW_TRACKING_URI` is set, the application will attempt to connect to the MLflow server at startup. If the server is unreachable, the application will log a warning and continue running without tracing.

- You can control how long the application waits for the MLflow server by setting `MLFLOW_HEALTH_CHECK_TIMEOUT` (in seconds, default: `5`).

#### PostgreSQL Configuration

This agent requires a PostgreSQL database for conversation persistence. Add the following to your `.env`:

```ini
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
```

| Variable            | Description                            | Example         |
|---------------------|----------------------------------------|-----------------|
| `POSTGRES_HOST`     | Database hostname                      | `localhost`     |
| `POSTGRES_PORT`     | Database port                          | `5432`          |
| `POSTGRES_DB`       | Database name for conversation history | `agent_memory`  |
| `POSTGRES_USER`     | Database username                      | `postgres`      |
| `POSTGRES_PASSWORD` | Database password                      | (your password) |

**Setting up a local PostgreSQL instance:**

Option 1 -- Docker/Podman:

```bash
docker run --name postgres-agent \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DB=agent_memory \
  -p 5432:5432 \
  -d postgres:16
```

Option 2 -- Local PostgreSQL (macOS):

```bash
brew install postgresql@16
brew services start postgresql@16
createdb agent_memory
```

The database tables are created automatically on first run -- no manual schema setup is needed.

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
cd agents/langgraph/react_with_database_memory
make run-app           # fails if port is already in use and print steps TO-DO
```

#### Interactive CLI

For terminal-based testing without a browser:

```bash
cd agents/langgraph/react_with_database_memory
make run-cli
```

This launches an interactive prompt where you can pick predefined questions or type your own. Tool calls and results are
displayed inline with colored output. Your `thread_id` is shown at startup so you can resume conversations later.

## Deploying to OpenShift

### Setup

```bash
cd agents/langgraph/react_with_database_memory
make init
```

### Configuration

Edit `.env` with your model endpoint, PostgreSQL credentials, and container image:

```ini
API_KEY = your-api-key-here
BASE_URL = https://your-model-endpoint.com/v1
MODEL_ID = llama-3.1-8b-instruct
CONTAINER_IMAGE = quay.io/your-username/langgraph-db-memory-agent:latest

POSTGRES_HOST = your-postgres-host.com
POSTGRES_PORT = 5432
POSTGRES_DB = agent_memory
POSTGRES_USER = your_db_user
POSTGRES_PASSWORD = your_db_password
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `CONTAINER_IMAGE` -- full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/langgraph-db-memory-agent:latest`
    - Docker Hub: `docker.io/your-username/langgraph-db-memory-agent:latest`
    - GHCR: `ghcr.io/your-org/langgraph-db-memory-agent:latest`

  > **Note:** OpenShift must be able to pull the container image. Make the image **public**, or configure
  an [image pull secret](https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html)
  for private registries.

- `POSTGRES_HOST` - PostgreSQL database hostname (must be accessible from the cluster)
- `POSTGRES_PASSWORD` - stored as a Kubernetes secret (never in plain-text manifests)

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

No Podman, Docker, or registry account needed -- just the `oc` CLI.

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
oc get route langgraph-db-memory-agent -o jsonpath='{.spec.host}'
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
  -d '{"messages": [{"role": "user", "content": "I will tell you a story about blue eyed Johnny! He liked ice creams. End."}], "stream": false, "thread_id": "test-conversation-1"}'
```

Continue the conversation with the same `thread_id`:

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What did we talk about?"}], "stream": false, "thread_id": "test-conversation-1"}'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What did we talk about?"}], "stream": true, "thread_id": "test-conversation-1"}'
```

Pretty Printed Stream:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is the best cluster hosting service?"}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

**Note:** The `thread_id` field is optional. When omitted, the agent runs without persistence (no conversation history
is saved). When provided, messages are stored in PostgreSQL and retrieved on subsequent requests with the same
`thread_id`.

### GET /health

```bash
curl http://localhost:8000/health
```

## Architecture

This agent combines three key components:

1. **LangGraph ReACT Agent** -- reasoning and action loop with tool calling
2. **PostgresSaver Checkpointer** -- persistent conversation memory in PostgreSQL
3. **ChatOpenAI** -- OpenAI-compatible LLM client (connects to Llama Stack or any OpenAI-compatible endpoint)

```
User Input --> LangGraph Agent --> ChatOpenAI --> LLM (Ollama/OpenAI)
                   |                               |
            PostgreSQL <-- PostgresSaver <-- Messages & State
```

**Message Flow:**

1. User sends message with optional `thread_id`
2. Agent loads conversation history from PostgreSQL (if thread exists)
3. FIFO trimmer keeps only the last 5 messages for the LLM context window
4. Agent processes with ReACT loop (reason, act, observe)
5. New messages saved to PostgreSQL
6. Response returned to user

**Customization:**

Edit `src/react_with_database_memory/agent.py`:

```python
# Change context window size (default: 5 messages)
max_messages_in_context = 10  # Keep last 10 messages

# Change default system prompt
default_system_prompt = "You are a specialized assistant..."
```

### Inspecting Conversation History

To list all stored threads or view messages in a specific thread:

1. Edit `examples/query_existing_deployment.py`
2. To list all threads, leave `thread_id` empty:
   ```python
   thread_id = ""
   ```
   To view messages for a specific thread, set it:
   ```python
   thread_id = "123e4567-e89b-12d3-a456-426614174000"
   ```
3. Run the script:
   ```bash
   uv run python examples/query_existing_deployment.py
   ```

### Deleting Thread History

To permanently delete a conversation thread (or all threads), use the provided script:

1. Edit `examples/clear_thread_history.py`
2. To delete a specific thread, set the `thread_id`:
   ```python
   thread_id = "123e4567-e89b-12d3-a456-426614174000"
   ```
   To delete **all** threads, leave it empty:
   ```python
   thread_id = ""
   ```
3. Run the script:
   ```bash
   uv run python examples/clear_thread_history.py
   ```

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph Checkpointers](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangChain Documentation](https://python.langchain.com/)
- [Llama Stack Documentation](https://llama-stack.readthedocs.io/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
