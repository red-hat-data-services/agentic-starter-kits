<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# CI Failure Summarizer

</div>

---

## What this agent does

Lightweight **spike** for a daily QG4 CI failure summarizer. It keeps the standard FastAPI contract
(`POST /chat/completions`, `GET /health`) from the DB-memory template and adds a manual summarization trigger
(`POST /summarize`).

**Spike scope (implemented):**

- **QG4 workflow targeting** — ingest the latest (or specified) run from `GITHUB_REPOSITORY` / `GITHUB_WORKFLOW`
- **Deterministic grouping** — fingerprint failures by workflow, job, step, branch, event, and QG label (outside the LLM)
- **PostgreSQL incident store** — dedicated `ci_incidents` and `ci_summary_history` tables (separate from LangGraph chat checkpoints)
- **LLM or metadata-only summary** — triage text via configured model endpoint, with fallback when logs or LLM are unavailable
- **Slack triage post** — top-level incoming webhook message with workflow links and grouped failure context
- **Manual trigger only** — `POST /summarize`, `examples/trigger_summary.py`, or `examples/trigger_daily_summary_after_qg4.sh`

**Explicitly out of scope for this spike:**

- No Slack thread replies or per-job threaded follow-ups
- No Jira write-back or ticket creation
- No automated remediation execution
- No built-in scheduler or CronJob (trigger manually after QG4 completes)
- No auth on `/summarize` (same open pattern as other template agents)

**Spike operational posture:** `/summarize` is **unauthenticated** and **manual-trigger only** — call it after QG4 completes (see examples below). There is no built-in scheduler, API key gate, or production hardening; treat the route as operator-only on a trusted network.

**Known limitations:**

- GitHub ingest is **unauthenticated by default**. Public workflow metadata (runs, jobs, steps) works without a token.
- Unauthenticated GitHub API access is subject to **low rate limits** (60 requests/hour per IP). Expect `403`/`rate limit` errors under heavy use; set `GITHUB_TOKEN` to raise limits.
- Job log download often returns **HTTP 403** without repository admin access or `GITHUB_TOKEN`. The summarizer degrades gracefully to metadata-only triage.
- Slack delivery is a single top-level message, not a thread under an existing alert.

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

### Initiating base

`make init` creates a `.env` file from `.env.example`. Set your environment variables in the `.env` file.

```bash
cd agents/langgraph/templates/ci_failure_summarizer
make init
```

### Creating environment

Now you will remove old .venv and create new. Next dependencies will be installed.

```bash
make env
```

### Spike configuration

In addition to the standard LLM and PostgreSQL settings, configure GitHub and Slack targets in `.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `GITHUB_REPOSITORY` | yes | `owner/repo` for the public repository to monitor (default: `red-hat-data-services/agentic-starter-kits`) |
| `GITHUB_WORKFLOW` | no | Workflow display name (default: `QG4: Agent Deployment Integration Tests`) |
| `SLACK_WEBHOOK_URL` | no | Incoming webhook URL for triage summaries (omit or leave empty to dry-run without posting) |
| `GITHUB_TOKEN` | no | Optional PAT for authenticated job log download when admin access is available |
| `GITHUB_WORKFLOW_FILE` | no | Fallback workflow file if name resolution fails (default: `agent-deployment-test.yaml`) |

These variables are declared in `agent.yaml` and `values.yaml` for Helm deployment.

### Manual daily summary trigger

After QG4 completes (scheduled ~11 PM EDT or via `workflow_dispatch`), trigger a summary manually:

**HTTP (agent running locally or on OpenShift):**

```bash
# Dry-run: build summary without Slack
curl -X POST http://localhost:8000/summarize \
  -H 'Content-Type: application/json' \
  -d '{"post_to_slack": false}'

# Target a specific workflow run
curl -X POST http://localhost:8000/summarize \
  -H 'Content-Type: application/json' \
  -d '{"run_id": 123456789, "post_to_slack": true}'
```

**Python script (no HTTP server required):**

```bash
cd agents/langgraph/templates/ci_failure_summarizer
uv run python examples/trigger_summary.py --no-slack
```

**Shell helper (post-QG4 example):**

```bash
chmod +x examples/trigger_daily_summary_after_qg4.sh
AGENT_URL=https://<route-host> POST_TO_SLACK=false ./examples/trigger_daily_summary_after_qg4.sh
```

Response fields include `summary_text`, grouped `failures` (with fingerprints and occurrence counts), `slack_posted`, and `logs_available`.

### Tracing (optional)

Tracing is optional. If MLflow tracing is required, enable it by uncommenting and setting the following environment variables in the `.env` file.

#### Tracing with a local MLflow server

```ini
MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="langgraph-ci-failure-summarizer-agent"
MLFLOW_HTTP_REQUEST_TIMEOUT=2
MLFLOW_HTTP_REQUEST_MAX_RETRIES=0
```

Then start the MLflow server in a separate terminal:

```bash
# Start the MLflow server
uv run --extra tracing mlflow server --port 5000
```

When `MLFLOW_TRACKING_URI` is set, `make run-app` and `make run-cli` will automatically install the tracing dependency.

#### Tracing with an OpenShift MLflow server

To enable tracing and logging with MLflow on your OpenShift cluster, add the following environment variables to your `.env` file:

```ini
MLFLOW_TRACKING_URI="https://<openshift-dashboard-url>/mlflow"
MLFLOW_TRACKING_TOKEN="<your-openshift-token>"
MLFLOW_EXPERIMENT_NAME="langgraph-ci-failure-summarizer-agent"
MLFLOW_TRACKING_INSECURE_TLS="true"
MLFLOW_WORKSPACE="default"
```

**Notes:**

- `MLFLOW_TRACKING_URI` - URL of your MLflow server. For local development, use `http://localhost:5000`. If using MLflow on an OpenShift cluster, replace `<openshift-dashboard-url>` with your cluster's data science gateway URL.
- `MLFLOW_TRACKING_TOKEN` - Required for OpenShift only. Your OpenShift authentication token, obtained from the OpenShift console.
- `MLFLOW_EXPERIMENT_NAME` - A descriptive name for your experiment (e.g., "langgraph-ci-failure-summarizer-agent")
- `MLFLOW_TRACKING_INSECURE_TLS` - Required for OpenShift only. Set to `"true"` if your cluster does not use trusted certificates.
- `MLFLOW_WORKSPACE` - Required for OpenShift only. Project name.

- Tracing is optional; if you do not set `MLFLOW_TRACKING_URI`, the application will run without MLflow logging.

- If `MLFLOW_TRACKING_URI` is set, the application will attempt to connect to the MLflow server at startup. If the server is unreachable, the application will log a warning and continue running without tracing.

- You can control how long the application waits for the MLflow server by setting `MLFLOW_HEALTH_CHECK_TIMEOUT` (in seconds, default: `5`).

### PostgreSQL Configuration

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

### Setup Ollama

This will install ollama if it is not installed already. Then pull needed models for local work.
The default model is `llama3.1:8b`. To use a different model, pass `MODEL=`:
`make ollama MODEL=llama3.2:3b`

```bash
make ollama
```

### Run OGX server

> **Keep this terminal open** – the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.

```bash
make ogx-server
```

### Run the interactive web application

> **Keep this terminal open** – the app needs to keep running.
> You should see output indicating the app started on `http://localhost:8000`.

```bash
cd agents/langgraph/templates/ci_failure_summarizer
make run-app           # fails if port is already in use; use make run-app-fresh to restart
```

### Interactive CLI

For terminal-based testing without a browser:

```bash
cd agents/langgraph/templates/ci_failure_summarizer
make run-cli
```

This launches an interactive prompt where you can pick predefined questions or type your own. Tool calls and results are
displayed inline with colored output. Your `thread_id` is shown at startup so you can resume conversations later.

## Deploying to OpenShift

### ci-testing deployment notes

QG4 agent deployment tests run in the **`ci-testing`** namespace on the demo OpenShift cluster. To exercise this spike against real QG4 failures:

1. Deploy the summarizer to the same cluster (or locally with network access to GitHub and your model endpoint).
2. Point `GITHUB_REPOSITORY` at `red-hat-data-services/agentic-starter-kits` and keep the default `GITHUB_WORKFLOW`.
3. Configure `SLACK_WEBHOOK_URL` with a test-channel webhook for spike validation.
4. Reuse the shared PostgreSQL service used by other DB-memory agents (`POSTGRES_*` from cluster vars) or provision a dedicated database.
5. After the nightly QG4 workflow finishes, call `POST /summarize` on the deployed route:

```bash
ROUTE="$(oc -n ci-testing get route langgraph-ci-failure-summarizer-agent -o jsonpath='{.spec.host}')"
curl -X POST "https://${ROUTE}/summarize" \
  -H 'Content-Type: application/json' \
  -d '{"post_to_slack": false}'
```

This spike does not register itself in the QG4 matrix yet; deploy and trigger manually for validation.

### Setup

```bash
cd agents/langgraph/templates/ci_failure_summarizer
make init
```

### Configuration

Edit `.env` with your model endpoint, PostgreSQL credentials, and container image:

```ini
API_KEY = your-api-key-here
BASE_URL = https://your-model-endpoint.com/v1
MODEL_ID = llama-3.1-8b-instruct
CONTAINER_IMAGE = quay.io/your-username/langgraph-ci-failure-summarizer-agent:latest

POSTGRES_HOST = your-postgres-host.com
POSTGRES_PORT = 5432
POSTGRES_DB = agent_memory
POSTGRES_USER = your_db_user
POSTGRES_PASSWORD = your_db_password
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`. For local OGX, use `http://localhost:8321/v1`
- `MODEL_ID` - model identifier available on your endpoint
  - **Local OGX:** requires `ollama/` prefix (e.g., `ollama/Llama3.1:8B`)
  - **Cluster deployment:** discover available models via `curl $BASE_URL/models` or check your model serving dashboard
- `CONTAINER_IMAGE` -- full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

  - Quay.io: `quay.io/your-username/langgraph-ci-failure-summarizer-agent:latest`
  - Docker Hub: `docker.io/your-username/langgraph-ci-failure-summarizer-agent:latest`
  - GHCR: `ghcr.io/your-org/langgraph-ci-failure-summarizer-agent:latest`

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
oc get route langgraph-ci-failure-summarizer-agent -o jsonpath='{.spec.host}'
```

#### Remove deployment (`make undeploy`)

```bash
make undeploy
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for more details.

## Tests

### Unit tests

Focused spike tests (no live GitHub, Slack, or PostgreSQL required):

| Test file | Covers |
| --- | --- |
| `test_github_client.py` | Workflow path resolution, metadata error surfacing, job parsing, log degradation |
| `test_grouping.py` | Deterministic fingerprinting and grouping |
| `test_summary_composer.py` | LLM fallback and metadata-only summary formatting |
| `test_slack_notifier.py` | Slack Block Kit payload composition |
| `test_orchestrator.py` | End-to-end orchestration, explicit `run_id` workflow validation |
| `test_incident_store.py` | Incident upsert and summary history persistence (mocked DB) |
| `test_summarize_api.py` | `/summarize` request models and route behavior |

```bash
make test
# or without make:
uv run --extra dev python -m pytest tests/ --ignore=tests/integration --ignore=tests/behavioral -q
```

### Behavioral tests

Behavioral tests validate tool selection, response quality, latency, and reliability against a live agent. They require MLflow tracing to extract tool_calls from trace spans.

```bash
CI_FAILURE_SUMMARIZER_AGENT_URL=https://<agent-route> \
MLFLOW_TRACKING_URI=<mlflow-uri> \
MLFLOW_EXPERIMENT_NAME=<experiment> \
MLFLOW_TRACKING_TOKEN=$(oc whoami -t) \
pytest tests/behavioral/ -v
```

Skip slow pass@k tests with `-m "not slow"`.

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

### POST /summarize

Manual CI failure summarization trigger (spike-specific). **Unauthenticated** — intended for operator/cron triggers on a trusted network, not public exposure.

```bash
curl -X POST http://localhost:8000/summarize \
  -H 'Content-Type: application/json' \
  -d '{"post_to_slack": false}'
```

Optional body fields:

- `run_id` — target a specific workflow run (defaults to latest QG4 run); must belong to the configured `GITHUB_WORKFLOW` / workflow file
- `post_to_slack` — set `false` to skip Slack webhook delivery

## Architecture

This agent has two paths:

### Chat completions (standard template)

1. **LangGraph ReACT Agent** — reasoning loop inherited from the DB-memory scaffold (no chat tools in this spike)
2. **PostgresSaver Checkpointer** — persistent conversation memory in PostgreSQL
3. **ChatOpenAI** — OpenAI-compatible LLM client

### CI summarization (spike)

```text
POST /summarize  (manual, unauthenticated — operator/cron trigger only)
    --> GitHubActionsClient (public metadata; logs degrade on 403)
    --> grouping.py (deterministic fingerprints)
    --> IncidentStore (ci_incidents + ci_summary_history; connection-per-call spike trade-off)
    --> summary_composer.py (LLM or metadata-only fallback)
    --> slack_notifier.py (incoming webhook, top-level post only)
```

**Chat customization:** edit `src/ci_failure_summarizer/agent.py` for context window size and default system prompt.

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
- [OGX Documentation](https://ogx-ai.github.io/docs/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
