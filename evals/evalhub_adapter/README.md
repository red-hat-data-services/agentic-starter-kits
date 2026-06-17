# EvalHub Adapter

Integration layer that bridges the existing pytest-based eval harness to
[EvalHub](https://github.com/redhat-ai-services/evalhub)'s Kubernetes
orchestration on OpenShift. Designed to run **on-cluster** as an EvalHub job.

## Who this is for

AI engineers, evaluation owners, and platform engineers who want to run scored
behavioral evaluations against agentic-starter-kit agents via EvalHub on
OpenShift.

## Architecture

Four files that do one thing: translate EvalHub's `JobSpec` into harness
calls and report results back.

| File | Role |
|------|------|
| `adapter.py` | `AgenticEvalAdapter` — implements EvalHub's `FrameworkAdapter`. Drives the pipeline: INITIALIZING → LOADING_DATA → RUNNING_EVALUATION → POST_PROCESSING → PERSISTING_ARTIFACTS → results. Entry point: `main()`. |
| `config.py` | Maps job parameters and per-query fields into `TaskConfig`. Defines `AgenticEvalParams` (known_tools, forbidden_actions, max_latency_seconds, timeout_seconds, verify_ssl, fixtures_path, MLflow settings). |
| `evaluations.py` | Registry mapping evaluation IDs to fixture YAML filenames + scorer lists. Includes `agentic-tool-use` benchmark definition. |
| `__init__.py` | Exports `AgenticEvalAdapter`. |

## Inner loop vs outer loop

The same harness code (fixtures + scorers) can run in both loops. The
difference is execution context and operational purpose, not a completely
different test implementation.

| | Inner loop (local/CI) | Outer loop (EvalHub orchestration) |
|---|---|---|
| **What runs** | Harness tests/evals via pytest | Same harness logic via EvalHub adapter job |
| **Where** | Local machine or GitHub Actions | Kubernetes jobs on OpenShift |
| **Speed** | Seconds to minutes | Minutes to tens of minutes |
| **Primary use** | Fast developer feedback and merge gating | Scheduled/on-cluster evaluation and reporting |

EvalHub does **not** replace CI; it operationalizes the same evaluation logic
for cluster-native execution, tracking, and integration with EvalHub workflows.

## Design decisions

- **One adapter, all agents.** The adapter is agent-agnostic. Benchmark query
  files contain agent-specific `expected_tools`; each agent with different tools
  needs its own query files.
- **Runtime config via `JobSpec.parameters`.** Agent-specific settings
  (known_tools for hallucination detection, thresholds, forbidden actions) are
  passed at job submission time, not baked into fixtures.
- **No scoring logic here.** All scorers live in `harness/scorers/`. The adapter
  reuses them. Currently active: tool_selection, tool_sequence,
  hallucinated_tools, tool_call_validity. Wired but awaiting benchmarks:
  plan_coherence, completeness, latency, pii_leakage, policy_adherence,
  injection_resistance.

### Adding a new agent's fixtures

1. Create `agents/<framework>/templates/<agent_name>/evalhub/tool_use.yaml` with
   `queries`, `expected_tools`, `expected_elements`
2. Add a `COPY` line to `evals/evalhub_adapter/Containerfile`:
   `COPY agents/<framework>/templates/<agent_name>/evalhub/ ./fixtures/<short_name>/`
3. Use `fixtures_path: fixtures/<short_name>` in your eval submission YAML
4. Set `known_tools` in parameters to match the agent's available tools

## Container image

Build from the repo root using the provided Containerfile (UBI9 + PYTHONPATH
source layout so fixture paths resolve correctly):

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
ADAPTER_IMAGE="quay.io/<your-user>/evalhub-agentic-adapter:${IMAGE_TAG}"

podman build -t "${ADAPTER_IMAGE}" -f evals/evalhub_adapter/Containerfile .
podman push "${ADAPTER_IMAGE}"
```

This image runs as a batch-style EvalHub job (entrypoint only); it does not
run an HTTP server.

## Running on-cluster

EvalHub invokes `main()` in `adapter.py`. JobSpec loading is handled by
EvalHub's `FrameworkAdapter` base class (reads from `/meta/job.json`).

### Provider registration

Register the adapter as a custom provider via the EvalHub REST API
(`POST /api/v1/evaluations/providers`). The provider is tenant-scoped
and available immediately — no restart or operator changes needed.

See [EvalHub Server API — Providers](https://eval-hub.github.io/reference/server-api/)
for the full schema.

## End-to-end walkthrough (EvalHub orchestration)

Use this flow when you want to run a real on-cluster evaluation against one of
the agent templates in this repo.

> **Quick path:** `evals/evalhub_adapter/tests/run-e2e.sh` automates steps 1–7
> below. Set `REGISTRY_USER` and `OC_NAMESPACE` for your cluster, then run
> it. `MLFLOW_EXPERIMENT` is optional — the script auto-generates a unique
> name per run when unset. The script auto-discovers agent and EvalHub
> routes, builds/pushes the adapter image, registers the provider, submits
> jobs for both agents, polls for results, and cleans up the provider
> afterwards.

### 1) Prerequisites

- **EvalHub server >= 0.3.0** — the BYOF (Bring Your Own Framework) provider
  path this adapter uses requires server 0.3.0+. The operator-shipped image in
  RHOAI 3.4.0-ea may be 0.2.0 which accepts registrations but fails at job
  execution time. Workaround: replace the server image with
  `quay.io/evalhub/evalhub:0.3.0` (scale down the TrustyAI operator first to
  prevent reconciliation).
- `oc` login is active (`oc whoami` works)
- EvalHub is deployed and reachable (route or service URL)
- Target agent is deployed and reachable (for example, `react_agent`)
- You have push access to a container registry (for example, Quay) and your
  OpenShift cluster can pull that adapter image
- `evalhub` CLI is installed and on your `PATH`
  - The CLI is provided by the `eval-hub-sdk` package
  - Install from this repo root: `uv pip install .[evalhub,test-mlflow]`
  - Verify with `evalhub --version`

### 2) Build and push the adapter image

From repo root:

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
ADAPTER_IMAGE="quay.io/<your-user>/evalhub-agentic-adapter:${IMAGE_TAG}"

podman build -t "${ADAPTER_IMAGE}" -f evals/evalhub_adapter/Containerfile .
podman push "${ADAPTER_IMAGE}"
```

### 3) Configure EvalHub CLI

```bash
export OC_NAMESPACE="<your-namespace>"

evalhub config set base_url "https://<evalhub-route>"
evalhub config set token "$(oc whoami -t)"
evalhub config set tenant "${OC_NAMESPACE}"

evalhub health
```

### 4) Register a provider for this adapter image

Provider registration is not yet supported by the `evalhub` CLI
(`providers list`/`describe` only). Use the EvalHub REST API directly.

Create `provider-agentic.json` (reuses `ADAPTER_IMAGE` from step 2 and
`OC_NAMESPACE` from step 3):

```bash
export MLFLOW_TOKEN="$(oc whoami -t)"

cat > provider-agentic.json <<EOF
{
  "name": "Agentic Behavioral Evaluation",
  "title": "Agentic",
  "description": "Behavioral evaluation for agentic-starter-kit agents",
  "tags": ["agentic", "behavioral", "tool-use"],
  "benchmarks": [
    {
      "id": "agentic-tool-use",
      "name": "Agentic Tool Use",
      "description": "Evaluates tool selection and tool-call behavior",
      "category": "agentic",
      "metrics": [
        "tool_selection",
        "tool_sequence",
        "hallucinated_tools",
        "tool_call_validity"
      ],
      "num_few_shot": 0,
      "dataset_size": 5,
      "primary_score": {
        "metric": "tool_selection",
        "lower_is_better": false
      }
    }
  ],
  "runtime": {
    "k8s": {
      "Image": "${ADAPTER_IMAGE}",
      "Entrypoint": ["python", "-m", "evalhub_adapter.adapter"],
      "Env": [
        {"name": "MLFLOW_TRACKING_TOKEN", "value": "${MLFLOW_TOKEN}"},
        {"name": "MLFLOW_TRACKING_INSECURE_TLS", "value": "false"},
        {"name": "MLFLOW_WORKSPACE", "value": "${OC_NAMESPACE}"}
      ]
    }
  }
}
EOF
```

> **Note:** EvalHub does not support `secretKeyRef` in `Env`. Resolve secrets
> to literal values before registration. See `run-e2e.sh` for an automated
> example that reads the token from a Kubernetes secret at registration time.
>
> `MLFLOW_TRACKING_INSECURE_TLS` defaults to `"false"`. Set to `"true"` when
> using cluster-issued or self-signed certificates.

Register it:

```bash
curl -X POST "https://<evalhub-route>/api/v1/evaluations/providers" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H "X-Tenant: <your-namespace>" \
  -H "Content-Type: application/json" \
  --data @provider-agentic.json
```

Then capture the returned provider ID and verify:

```bash
evalhub providers list
```

Note: with `evalhub` CLI v0.1.5, `providers list/describe` shows a subset of
provider fields (`resource`, `name`, `description`, `benchmarks`). Fields such
as `title`, `tags`, and `runtime` are still accepted by the EvalHub API and
used server-side even if they are not fully surfaced in CLI output.

### 5) Create an eval run config

There are two different YAMLs in this flow:

- **Submission YAML (you create this):** e.g. `eval-react-agent.yaml`
  - Used by `evalhub eval run --config ...`
  - Defines model endpoint, provider, and benchmark `parameters`
- **Fixture YAMLs (already in repo/image):**
  - `agents/langgraph/templates/react_agent/evalhub/tool_use.yaml`
  - `agents/vanilla_python/templates/openai_responses_agent/evalhub/tool_use.yaml`
  - `agents/crewai/templates/websearch_agent/evalhub/tool_use.yaml`
  - `agents/langgraph/templates/agentic_rag/evalhub/tool_use.yaml`
  - `agents/langgraph/templates/react_with_database_memory/evalhub/tool_use.yaml`
  - `agents/llamaindex/templates/websearch_agent/evalhub/tool_use.yaml`
  - `agents/langflow/templates/simple_tool_calling_agent/evalhub/tool_use.yaml`
  - `agents/langgraph/templates/human_in_the_loop/evalhub/tool_use.yaml`
  - `agents/google/templates/adk/evalhub/tool_use.yaml`
  - These contain golden queries (`queries`, `expected_tools`,
    `expected_elements`) used by the adapter scorers
  - At image build time, these are copied into the adapter container under
    `fixtures/`:
    - `agents/langgraph/templates/react_agent/evalhub/*` -> `fixtures/langgraph_react/`
    - `agents/vanilla_python/templates/openai_responses_agent/evalhub/*` -> `fixtures/vanilla_python/`
    - `agents/crewai/templates/websearch_agent/evalhub/*` -> `fixtures/crewai_websearch/`
    - `agents/langgraph/templates/agentic_rag/evalhub/*` -> `fixtures/agentic_rag/`
    - `agents/langgraph/templates/react_with_database_memory/evalhub/*` -> `fixtures/langgraph_db_memory/`
    - `agents/llamaindex/templates/websearch_agent/evalhub/*` -> `fixtures/llamaindex_websearch/`
    - `agents/langflow/templates/simple_tool_calling_agent/evalhub/*` -> `fixtures/langflow_tool_calling/`
    - `agents/langgraph/templates/human_in_the_loop/evalhub/*` -> `fixtures/langgraph_hitl/`
    - `agents/google/templates/adk/evalhub/*` -> `fixtures/google_adk/`
  - You select which fixture set to use via `parameters.fixtures_path`

Create one file per agent. To evaluate both agents, submit two jobs.

**`eval-react-agent.yaml`** (LangGraph react_agent):

```yaml
name: agentic-tool-use-react-agent
description: EvalHub orchestration run for LangGraph react_agent
model:
  name: langgraph-react-agent
  url: https://<langgraph-react-agent-route>
benchmarks:
  - id: agentic-tool-use
    provider_id: <provider-id-from-registration>
    parameters:
      known_tools: ["search"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 8.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/langgraph_react
      mlflow_tracking_uri: https://<mlflow-route>
      mlflow_experiment_name: <agent-experiment>
```

**`eval-openai-responses-agent.yaml`** (vanilla_python openai_responses_agent):

```yaml
name: agentic-tool-use-openai-responses-agent
description: EvalHub orchestration run for vanilla_python openai_responses_agent
model:
  name: openai-responses-agent
  url: https://<openai-responses-agent-route>
benchmarks:
  - id: agentic-tool-use
    provider_id: <provider-id-from-registration>
    parameters:
      known_tools: ["search_price", "search_reviews"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 8.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/vanilla_python
      mlflow_tracking_uri: https://<mlflow-route>
      mlflow_experiment_name: <agent-experiment>
```

Notes:

- `model.url` must be the agent base URL (do not append `/chat/completions`)
- `fixtures_path` must match what the adapter image contains:
  - `react_agent` -> `fixtures/langgraph_react`
  - `openai_responses_agent` -> `fixtures/vanilla_python`
  - `crewai_websearch_agent` -> `fixtures/crewai_websearch`
  - `agentic_rag` -> `fixtures/agentic_rag`
  - `llamaindex_websearch` -> `fixtures/llamaindex_websearch`
  - `langflow_tool_calling` -> `fixtures/langflow_tool_calling`
  - `langgraph_hitl` -> `fixtures/langgraph_hitl`
  - `google_adk` -> `fixtures/google_adk`
  - These are relative to the container WORKDIR (`/opt/app-root/src`)
- `known_tools` should match the tools your target agent is allowed to use
- See [JobSpec parameters](#jobspec-parameters) for the full field reference

### 6) Submit and wait for the job

```bash
evalhub eval run --config eval-react-agent.yaml --wait --poll-interval 5
```

### 7) Check status and results

```bash
evalhub eval status
evalhub eval results <job-id> --format json
```

MLflow integration is required for this adapter flow. A successful run should
produce a non-null `mlflow_run_id` in `evalhub eval results`.

### 8) Interpreting results

All metrics are floats in the range **0.0–1.0** (1.0 = perfect).
`overall_score` is the mean of all metric values.

| Metric | What it measures |
|--------|-----------------|
| `tool_selection` | Did the agent call the correct tools for the query? |
| `tool_sequence` | Were tools called in the expected order? |
| `hallucinated_tools` | Did the agent avoid calling tools that don't exist? (1.0 = no hallucinations) |
| `tool_call_validity` | Were tool call arguments well-formed? |

Each metric also reports `pass_rate` (fraction of queries that passed the
threshold) and `min`/`max` across queries. These appear in the `metadata`
field of each result entry.

EvalHub does not have a results dashboard; use the CLI or REST API to
retrieve results. The `mlflow_run_id` in the results lets you navigate
directly to the MLflow run:

```text
https://<mlflow-route>/#/experiments/<experiment-id>/runs/<mlflow_run_id>
```

The adapter logs `overall_score`, `duration_seconds`, and each metric +
`<metric>_pass_rate` as MLflow metrics. Job parameters (`benchmark_id`,
`model_name`, `agent_url`, `num_queries`) are logged as MLflow params.

### MLflow troubleshooting (OpenShift)

If runs complete but `mlflow_run_id` is null, verify MLflow auth and workspace:

- Ensure `mlflow_tracking_uri` and `mlflow_experiment_name` are set in benchmark
  `parameters`.
- Ensure the adapter job has MLflow auth environment variables in provider
  runtime config:
  - `MLFLOW_TRACKING_TOKEN` (for route auth)
  - `MLFLOW_WORKSPACE` (required by RHOAI MLflow APIs)
  - `MLFLOW_TRACKING_INSECURE_TLS=true` when using cluster-issued/self-signed certs

**EvalHub Env limitation:** EvalHub's runtime Env spec only supports flat
`{"name": "...", "value": "..."}` pairs. Kubernetes-style `valueFrom` /
`secretKeyRef` references are **not** resolved — the token will arrive as an
empty string. Always resolve secret values before provider registration and
pass them as literal `value` strings. The `run-e2e.sh` script does this
automatically by reading the token from the agent's existing Kubernetes secret.

Common error signatures:

- `Missing Authorization header or X-Forwarded-Access-Token header.`
  - Fix: set `MLFLOW_TRACKING_TOKEN` in provider runtime env.
- `Workspace context is required`
  - Fix: set `MLFLOW_WORKSPACE` in provider runtime env.
- `MLFLOW_TRACKING_TOKEN is not set` (adapter startup warning)
  - The token was empty or absent in the pod environment. If you used
    `secretKeyRef` in the provider Env, replace it with a resolved literal
    value (see limitation above).
- Token shows as `"Value":""` in the provider response
  - Same cause: EvalHub did not resolve the `secretKeyRef`. Re-register the
    provider with the token as a plain `value`.
- `MLflow returned non-JSON (likely an OAuth redirect)` or
  `Expecting value: line 1 column 1 (char 0)`
  - The RHOAI OAuth proxy rejected an expired `MLFLOW_TRACKING_TOKEN` and
    returned an HTML login redirect instead of JSON. Refresh with a current
    token: `export MLFLOW_TOKEN=$(oc whoami -t)` and re-register the provider.
    The `run-e2e.sh` script prefers the current OC session token automatically.

Quick check from adapter logs:

```bash
oc logs -n <your-namespace> <eval-job-pod-name>
```

## JobSpec parameters

You do **not** create `JobSpec` directly. When you submit a config YAML with
`evalhub eval run --config ...`, EvalHub creates the `JobSpec` and delivers
it to the adapter at runtime (mounted at `/meta/job.json`). The adapter reads
agent-specific settings from the `parameters` block:

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `known_tools` | `list[str]` | `[]` | No | Tools the agent is allowed to use (for hallucination detection) |
| `forbidden_actions` | `list[str]` | `[]` | No | Actions the agent must not perform |
| `max_latency_seconds` | `float` | `10.0` | No | Threshold for the latency scorer |
| `timeout_seconds` | `float` | `30.0` | No | HTTP request timeout per query |
| `verify_ssl` | `bool` | `true` | No | TLS certificate verification. Setting to `false` requires `EVALHUB_ALLOW_INSECURE_TLS=true` in the environment. |
| `fixtures_path` | `str` | `fixtures` | No | Path to agent fixture YAMLs (relative to container WORKDIR) |
| `stream` | `bool` | `true` | No | Use SSE streaming to capture tool calls (see below) |
| `mlflow_tracking_uri` | `str` | — | **Yes** | MLflow server URL |
| `mlflow_experiment_name` | `str` | — | **Yes** | MLflow experiment for eval run logging. Use the agent's experiment (discovered from its deployment env `MLFLOW_EXPERIMENT_NAME`) so traces and eval metrics live together. |
| `mlflow_trace_experiment_name` | `str` | `mlflow_experiment_name` | No | Experiment to read agent traces from. Only set if traces are in a different experiment than `mlflow_experiment_name`. |

### Why streaming is the default

Agents define `ChatCompletionResponse` as the FastAPI `response_model`, which
only declares the standard OpenAI fields (`id`, `object`, `created`, `model`,
`choices`, `usage`). The agents _do_ build a `context` field carrying the
full message history (including tool calls), but Pydantic serialization strips
it because it is not declared on the model. The final `choices[0].message` is
a plain text response with no `tool_calls`.

Streaming (`stream=true`) bypasses Pydantic serialization entirely — agents
return a `StreamingResponse` with SSE chunks that include `delta.tool_calls`.
The harness runner accumulates these into `TaskResult.tool_calls`, which the
tool-use scorers then evaluate. Set `stream: false` only if the target agent
has been modified to expose tool calls in its non-streaming response model.

## MLflow integration

Two first-class integrations (require `mlflow_tracking_uri` and
`mlflow_experiment_name` in job parameters):

1. **Trace enrichment** (per-query) — `MLflowTraceClient` from
   `harness.mlflow_client` reads agent-side traces after each query to fill
   in token usage and any tool calls not captured via SSE streaming.
   Fault-tolerant: enrichment failures are logged but do not abort the query
   or affect scoring.
2. **Run logging** (per-job) — `_log_mlflow_run` writes aggregated scorer
   results (metrics, pass rates, overall score, duration) to MLflow as a run.
   On success, the returned MLflow run ID is propagated to EvalHub via
   `JobResults.mlflow_run_id` so `evalhub eval results` can surface it.

### Experiment design

The `run-e2e.sh` script discovers the agent's `MLFLOW_EXPERIMENT_NAME` from
its deployment env vars and uses the same experiment for eval metric logging.
This means agent traces and eval runs live in a single experiment — open the
experiment in MLflow to see both the traces tab (per-request agent traces)
and the runs tab (eval metric summaries) together.

The adapter container requires `MLFLOW_WORKSPACE` set in the provider runtime
env and uses mlflow >= 3.10 (workspace-aware SDK). The `run-e2e.sh` script
sets this automatically from the namespace.

## What works now

- `agentic-tool-use` benchmark: 5 golden queries per agent
  (e.g. `agents/langgraph/templates/react_agent/evalhub/tool_use.yaml`)
- `agentic-tool-use` runs 4 scorers: tool_selection, tool_sequence,
  hallucinated_tools, tool_call_validity. 6 additional scorers
  (plan_coherence, completeness, latency, pii_leakage, policy_adherence,
  injection_resistance) have dispatch wiring but no benchmark invokes them yet
- Config translation from EvalHub `JobSpec` → harness `TaskConfig`
- MLflow integration (trace enrichment + run logging)
- Containerfile for building the adapter image (UBI9, PYTHONPATH layout)
- Provider registration via EvalHub REST API
- asyncio nesting guard (thread-pool fallback for async callers)
- Agent-specific query files (LangGraph `search` tool, vanilla Python
  `search_price` + `search_reviews` tools, CrewAI `Web Search` tool,
  LlamaIndex `dummy_web_search` tool, LangGraph HITL `create_file` tool,
  Langflow `get_forecast` + `search_parks` + `park_alerts` tools,
  Google ADK `dummy_web_search` tool)
- Langflow `/api/v1/run` adapter support (`api_format=langflow_run`,
  `flow_id`, auto_login token acquisition)
- Unit tests (50) + integration tests (11) for adapter, config, evaluations,
  and orchestration pipeline

## What's planned

- Concurrent query execution (`asyncio.gather` with semaphore — queries
  currently run sequentially)
- Additional evaluation suites: coherence, safety, latency (query files
  not yet populated)
- GitHub Actions workflow for CI / EvalHub integration (RHAIENG-4158)
- Regression dashboard

## Dependencies

| Package | Version | Install extra | Required |
|---------|---------|---------------|----------|
| `eval-hub-sdk[adapter]` | `>=0.1.4` | `evalhub` | Yes |
| `httpx` | `>=0.27` | `evalhub` | Yes |
| `pyyaml` | `>=6.0` | `evalhub` | Yes |
| `mlflow` | `>=3.10.0` | `test-mlflow` | Yes (trace enrichment + run logging) |

For container builds or local development:

```bash
uv pip install .[evalhub,test-mlflow]
```

## Running tests

Tests stub `evalhub` imports if the package isn't installed (bootstrap
lives in `conftest.py` so it runs before any test module, regardless of
which files are selected). `uv pip install .[test]` alone is sufficient.

```bash
# Unit tests only (fast, no network)
pytest evals/evalhub_adapter/tests/ -m unit -v

# Integration tests (mocked HTTP, exercises full orchestration pipeline)
pytest evals/evalhub_adapter/tests/ -m integration -v

# All adapter tests
pytest evals/evalhub_adapter/tests/ -v
```
