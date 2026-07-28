# MLflow Tracing for Codex CLI on OpenShift

Extends the Codex CLI deployment with MLflow experiment tracking via the `@mlflow/codex` notify hook. Each agent turn is exported as a trace to MLflow, capturing inputs, outputs, token usage, and (when available) child spans for LLM calls and tool invocations.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Codex Pod (codex-mlflow:latest)                        │
│                                                         │
│  entrypoint.sh                                          │
│       │                                                 │
│       ▼                                                 │
│  setup-mlflow.sh                                        │
│   ├─ Load SA token for MLflow auth                      │
│   ├─ Create experiment via Python mlflow SDK             │
│   ├─ Write mlflow-tracing.json (tracking URI + exp ID)  │
│   ├─ Register notify hook in config.toml                │
│   └─ exec sleep infinity                                │
│                                                         │
│  oc exec → codex exec "prompt"                          │
│       │                                                 │
│       ▼                                                 │
│  codex-traced-exec.sh (wrapper)                         │
│   ├─ Set MLFLOW_TRACKING_TOKEN from SA token            │
│   ├─ Run codex exec with all args                       │
│   ├─ Extract session data from JSONL transcript         │
│   └─ Call mlflow-codex notify-hook with turn payload    │
│       │                                                 │
│       ▼                                                 │
│  @mlflow/codex  ─────────────────────────────────────►  │
└─────────────────────────────────────────────────────────┘
                                                    │
                                          HTTPS + SA token
                                          X-MLFLOW-WORKSPACE
                                                    │
                                                    ▼
                              ┌──────────────────────────────┐
                              │  MLflow (redhat-ods-apps)     │
                              │  /mlflow/api/2.0/mlflow/...   │
                              │                              │
                              │  Experiment: codex-traces    │
                              │  Auth: kubernetes-namespaced │
                              └──────────────────────────────┘
```

## Prerequisites

- Codex deployment running in a namespace (base image from [PR #251](https://github.com/red-hat-data-services/agentic-starter-kits/pull/251))
- MLflow deployed via RHOAI operator (reachable at `mlflow.redhat-ods-applications.svc.cluster.local:8443`)
- vLLM inference endpoint serving `/v1/responses` with tool calling enabled (e.g., Qwen3.6-27B with `qwen3_coder` parser)

## Image Build

The MLflow layer extends the base Codex image with Python 3.12, Node.js 20, MLflow SDK, and `@mlflow/codex`:

```bash
# Create ImageStream and BuildConfig
oc apply -f - <<EOF
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: codex-mlflow
---
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: codex-mlflow
spec:
  source:
    type: Binary
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Containerfile.mlflow
      from:
        kind: ImageStreamTag
        name: codex:latest
  output:
    to:
      kind: ImageStreamTag
      name: codex-mlflow:latest
EOF

# Build
oc start-build codex-mlflow --from-dir=. --follow
```

### Image Contents

| Layer | Package | Version | Purpose |
|-------|---------|---------|---------|
| Python | python3.12 + pip | 3.12.x | MLflow SDK, experiment creation |
| Node.js | Node.js from official tarball | 20.19.2 | `@mlflow/codex` notify hook CLI |
| MLflow SDK | `mlflow[kubernetes]` | >=3.14 | Trace export, experiment management |
| @mlflow/codex | Built from source (v3.14.0) | 3.14.0 | Codex notify hook for MLflow tracing |
| codex-traced-exec.sh | Shell wrapper | — | Triggers trace export after `codex exec` |

`@mlflow/codex` is built from source because the npm package (as of v3.14.0) lacks the `X-MLFLOW-WORKSPACE` header needed for RHOAI's kubernetes-namespaced auth (upstream issue: mlflow#23927).

## RBAC

Two ClusterRoleBindings are required:

1. **mlflow-tracing-reader** — K8s RBAC for SA token auth:
   ```bash
   oc apply -f rbac-mlflow.yaml
   ```

2. **openclaw-mlflow-traces** — MLflow API permissions for experiment/trace creation:
   ```bash
   oc adm policy add-cluster-role-to-user openclaw-mlflow-traces \
     system:serviceaccount:<namespace>:default
   ```

Both are needed. The first allows the SA token to authenticate; the second grants permission to create experiments and write traces via the MLflow REST API.

## Deployment Patch

Patch the existing Codex deployment to use the MLflow image:

```bash
# Add env vars
oc set env deployment/codex \
  MLFLOW_TRACKING_URI=https://mlflow.redhat-ods-applications.svc.cluster.local:8443/mlflow \
  MLFLOW_EXPERIMENT_NAME=codex-traces \
  MLFLOW_EXPERIMENT_ID=<experiment-id> \
  MLFLOW_TRACKING_AUTH=kubernetes-namespaced \
  MLFLOW_TRACKING_INSECURE_TLS=true

# Switch to MLflow image and chain setup-mlflow.sh after entrypoint
oc patch deployment codex --type=json -p '[
  {"op": "replace", "path": "/spec/template/spec/containers/0/image",
   "value": "image-registry.openshift-image-registry.svc:5000/<namespace>/codex-mlflow:latest"},
  {"op": "replace", "path": "/spec/template/spec/containers/0/args",
   "value": ["setup-mlflow.sh", "sleep", "infinity"]}
]'
```

The `MLFLOW_WORKSPACE` env var is auto-set to the pod's namespace via `fieldRef: metadata.namespace`.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MLFLOW_TRACKING_URI` | Yes | — | MLflow server URL (include `/mlflow` path prefix) |
| `MLFLOW_EXPERIMENT_NAME` | No | `codex-traces` | Experiment name for auto-creation |
| `MLFLOW_EXPERIMENT_ID` | Yes | — | Numeric experiment ID (takes precedence over project-level config) |
| `MLFLOW_TRACKING_AUTH` | No | `kubernetes-namespaced` | Auth plugin for SA token |
| `MLFLOW_TRACKING_INSECURE_TLS` | No | `false` | Skip TLS verification (cluster-internal) |
| `MLFLOW_WORKSPACE` | Auto | Pod namespace | Namespace for `X-MLFLOW-WORKSPACE` header |

## Usage

### Traced Execution

Use the wrapper script for automatic trace export:

```bash
oc exec deployment/codex -- bash -c '
  codex-traced-exec.sh \
    --model qwen3.6-27b \
    -c "model_provider=\"vllm\"" \
    "explain what 2+2 equals"
'
```

### Manual Trace Export

If using `codex exec` directly (e.g., interactive mode), manually trigger the notify hook:

```bash
oc exec deployment/codex -- bash -c '
  export MLFLOW_TRACKING_TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
  export NODE_TLS_REJECT_UNAUTHORIZED=0
  mlflow-codex notify-hook '"'"'{"type":"agent-turn-complete","thread-id":"<session-id>","input-messages":["<prompt>"],"last-assistant-message":"<response>"}'"'"'
'
```

### Querying Traces

```bash
# Via MLflow REST API
curl -sk -H "Authorization: Bearer $TOKEN" \
  -H "X-MLFLOW-WORKSPACE: <namespace>" \
  "https://mlflow.../mlflow/api/2.0/mlflow/traces?experiment_ids=<id>&max_results=10"

# Via Python SDK
python3 -c "
import mlflow
mlflow.set_tracking_uri('...')
client = mlflow.MlflowClient()
traces = client.search_traces(experiment_ids=['<id>'])
for t in traces:
    print(t.info.request_id, t.info.status)
"
```

## Trace Schema

Each Codex turn produces a trace with the following structure:

```
Trace (request_id: tr-...)
├── experiment_id: "54"
├── status: OK
├── timestamp_ms: 1784661353172
├── execution_time_ms: 10093
├── request_metadata:
│   ├── mlflow.traceInputs: "<user prompt>"
│   ├── mlflow.traceOutputs: "<assistant response>"
│   ├── mlflow.trace.session: "<codex session uuid>"
│   ├── mlflow.trace.user: ""
│   ├── mlflow.trace.tokenUsage:
│   │   ├── input_tokens: 10198
│   │   ├── output_tokens: 369
│   │   └── total_tokens: 10567
│   └── mlflow.trace_schema.version: "3"
└── spans:
    └── codex_conversation (AGENT)
        ├── inputs: "<user prompt>"
        ├── outputs: "<assistant response>"
        └── attributes: { model: "qwen3.6-27b" }
            └── [child spans when tool calls present]:
                ├── llm_call (LLM) — model inference
                ├── function_call (TOOL) — apply_patch, shell
                └── function_call_output (TOOL) — tool results
```

### Span Types

| Type | When Created | Contains |
|------|-------------|----------|
| `codex_conversation` (AGENT) | Every turn | Root span, wraps the entire turn |
| `llm_call` (LLM) | Model inference | Model name, messages, token usage |
| `function_call` (TOOL) | Tool invocation | Tool name (apply_patch, shell), arguments |
| `function_call_output` (TOOL) | Tool result | Execution output, exit code |

Child spans are created when the `@mlflow/codex` notify hook can read the session JSONL transcript and finds function call records. Without tool calls (e.g., pure Q&A), only the root `codex_conversation` span is present.

## Known Issues

### `codex exec` Does Not Fire Notify Hooks

The `codex exec` (non-interactive) mode does not trigger the `notify` hook configured in `config.toml`. This is a Codex CLI limitation — notify hooks only fire in interactive mode. The `codex-traced-exec.sh` wrapper works around this by manually extracting session data and calling `mlflow-codex notify-hook` after completion.

### Project-Level Config Precedence

`@mlflow/codex` resolves config in this order:
1. `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_ID` environment variables
2. `$CWD/.codex/mlflow-tracing.json` (project-level)
3. `~/.codex/mlflow-tracing.json` (user-level)

The `mlflow-codex setup --non-interactive` command writes to the project-level config (CWD) with incorrect defaults (`localhost:5000`, experiment ID `0`). The `MLFLOW_EXPERIMENT_ID` env var in the deployment spec overrides this.

### Model Tool Call Support

Qwen3-8B via vLLM did not reliably generate tool calls in `codex exec` mode, producing single-span traces. Qwen3.6-27B (served via `docker.io/vllm/vllm-openai:v0.25.1` with `--tool-call-parser qwen3_coder --tensor-parallel-size 2`) is the current recommended model for multi-span traces with tool call child spans.

### OGX Backend Comparison

OGX endpoints were not available in the test namespace. The vLLM-direct path was validated end-to-end. OGX comparison is deferred to when an OGX endpoint is deployed in a namespace with MLflow tracing configured. The trace schema is backend-agnostic — `@mlflow/codex` captures traces at the Codex CLI level, not the inference backend level.

## Files

| File | Description |
|------|-------------|
| `Containerfile.mlflow` | Image layer with Python 3.12, Node.js 20, MLflow SDK, @mlflow/codex |
| `setup-mlflow.sh` | Post-entrypoint setup: SA token, experiment, notify hook, config fixups |
| `rbac-mlflow.yaml` | ClusterRole + RoleBinding for SA token auth |
| `deployment-mlflow-patch.yaml` | Strategic merge patch for env vars |
| `codex-traced-exec.sh` | Wrapper for `codex exec` that triggers trace export |
| `mlflow-tracing.md` | This document |
