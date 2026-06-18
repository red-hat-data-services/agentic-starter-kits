# EvalHub Adapter E2E From Local (Runbook)

This runbook captures what you need to execute the EvalHub adapter E2E tests from your local machine against OpenShift.

## Scope

- Runs `evals/evalhub_adapter/tests/run-e2e.sh`
- Validates both agents:
  - `langgraph-react-agent`
  - `openai-responses-agent`
- Uses EvalHub orchestration and MLflow logging

## What this script already does for you

The script includes a preflight phase and then automates:

1. Environment checks (tools, cluster auth, namespace access)
2. Route discovery (EvalHub, both agents, MLflow)
3. Adapter image build + push
4. Provider registration in EvalHub
5. Job submission for both agents
6. Polling + result collection
7. Provider cleanup

If any hard preflight check fails, the script exits early.

## CI/CD gating alignment

The repository includes `.github/workflows/eval-gating.yml` for inner-loop CI:

- **Deterministic gate (required)**: runs adapter unit/integration tests in CI.
- **Cluster btests (conditional)**: runs the shared pytest behavioral suite
  against deployed agents when cluster credentials are configured.

EvalHub orchestration remains an outer-loop evaluation path and is not part of
the CI merge gate.

## Prerequisites

### 1) Local tools

Required binaries on your `PATH`:

- `oc`
- `evalhub`
- `podman`
- `python3`
- `curl`
- `git`

Install Python dependencies from repo root:

```bash
cd /path/to/agentic-starter-kits
uv pip install .[evalhub,test-mlflow]
```

### 2) OpenShift access

- Active cluster login:

```bash
oc whoami
```

- Access to target namespace:

```bash
oc get namespace <your-namespace>
```

### 3) Pick the right namespace

Use a namespace where these routes are available (or provide explicit overrides):

- EvalHub route
- `langgraph-react-agent` route
- `openai-responses-agent` route
- MLflow route or discoverable MLflow URI

Quick route check:

```bash
NS=<your-namespace>
oc get route -n "$NS" -o custom-columns=NAME:.metadata.name,HOST:.spec.host --no-headers \
  | rg 'eval|react|openai|mlflow'
```

### 4) Container registry auth

You need push access to Quay (or your configured registry):

```bash
podman login quay.io
```

### 5) Token requirements

- `oc whoami -t` must return a valid token
- Script prefers current OC token for MLflow auth (`MLFLOW_TOKEN`)
- If MLflow auth fails, refresh token and rerun

## Step-by-step execution

### 1) Move to repo + branch

```bash
cd /path/to/agentic-starter-kits
# optional: git checkout <your-working-branch>
```

### 2) Run E2E with required env vars

```bash
cd evals/evalhub_adapter/tests
REGISTRY_USER=<your-quay-user> \
OC_NAMESPACE=<your-namespace> \
./run-e2e.sh
```

### Optional deploy helper flags

If you use `components/evalhub/deploy.sh` before E2E, these flags are useful
for shared CI-like clusters:

- `DISABLE_OPERATOR_SCALE_DOWN=true` to avoid scaling down TrustyAI operator
- `EVALHUB_INSECURE_SKIP_VERIFY=true` only when the sidecar must skip TLS verification
- `SKIP_PULL_SECRET=true` when image pull secrets are managed separately
- `PULL_SECRET_NAME=<name>` to use a custom pull secret

### 3) If route autodiscovery is wrong, override explicitly

```bash
REGISTRY_USER=<your-quay-user> \
OC_NAMESPACE=<your-namespace> \
EVALHUB_ROUTE=<evalhub-host> \
REACT_AGENT_ROUTE=<react-agent-host> \
OPENAI_AGENT_ROUTE=<openai-agent-host> \
MLFLOW_TRACKING_URI=https://<mlflow-host> \
./run-e2e.sh
```

### 4) Optional TLS toggle for MLflow route

Only use for development/testing environments with self-signed or cluster-issued cert behavior:

```bash
MLFLOW_INSECURE_TLS=true \
REGISTRY_USER=<your-quay-user> \
OC_NAMESPACE=<your-namespace> \
./run-e2e.sh
```

## What success looks like

- Preflight prints `Preflight passed` (or warnings only)
- Adapter image builds and pushes
- Provider registration returns a provider ID
- Both eval jobs complete
- `evalhub eval results <job-id> --format json` returns scores
- Result payload includes non-null `mlflow_run_id`

## Helpful verification commands

```bash
evalhub eval status
evalhub eval results <job-id> --format json
```

If needed, inspect adapter job logs:

```bash
oc get pods -n <your-namespace> | rg eval
oc logs -n <your-namespace> <eval-job-pod-name>
```

## Findings from review (important)

1. Test dependency nuance:
   - In a clean environment, `uv sync --extra test` can fail two MLflow-specific unit tests (`TestLogMlflowRun`) because `mlflow` is not in `test` extra.
   - If running adapter unit tests locally, prefer:

```bash
uv run --extra test --extra test-mlflow pytest evals/evalhub_adapter/tests -m unit -v
```

1. Localhost is blocked by URL validation:
   - Adapter currently rejects `localhost`, `127.0.0.1`, etc. for `agent_url` and `mlflow_tracking_uri`.
   - This flow is intended for on-cluster endpoints.

2. MLflow run URL fallback:
   - If MLflow experiment lookup fails, printed deep link may be less reliable.
   - Use `mlflow_run_id` from EvalHub results as source of truth.

## Common failure modes and fixes

- `evalhub: command not found`
  - `uv pip install .[evalhub,test-mlflow]`

- `namespace not found or not accessible`
  - Verify `oc project <ns>` permissions

- `podman not logged in to quay.io`
  - `podman login quay.io`

- `Could not discover EvalHub/agent/MLflow route`
  - Pass explicit route env vars

- `MLflow token appears invalid (401/403)`
  - `export MLFLOW_TOKEN=$(oc whoami -t)` and rerun script

- `mlflow_run_id` is null
  - Verify provider runtime env includes `MLFLOW_TRACKING_TOKEN` and `MLFLOW_WORKSPACE`
  - Verify MLflow URI is reachable from cluster namespace

## Quick copy/paste command

```bash
cd /path/to/agentic-starter-kits/evals/evalhub_adapter/tests && \
REGISTRY_USER=<your-quay-user> \
OC_NAMESPACE=<your-namespace> \
./run-e2e.sh
```
