# MLflow Tracing for OpenClaw

> Tested: 2026-10-08 on OpenShift 4.22 with `ghcr.io/openclaw/openclaw@sha256:d0ded1dd76939b2bf4d67ef2d13247b8b160aa5666331d4a0b0e58811182cbb8` (2026.9.8), vLLM (Red Hat AI Inference Server 3.3, CPU) serving `Qwen2.5-0.5B-Instruct`, RHOAI 3.3.1 MLflow
>
> Previously tested: 2026-06-17 on OpenShift 4.19 (ROSA) with OpenClaw 2026.6.5, vLLM `gpt-oss-120b`, RHOAI MLflow 3.x

OpenClaw natively emits OpenTelemetry (OTLP) traces via its `diagnostics-otel` plugin — no custom instrumentation, no Python hooks, no stop scripts. The [`overlays/mlflow-tracing/`](../overlays/mlflow-tracing/) Kustomize overlay in this repo deploys OpenClaw with an OTel collector sidecar that forwards spans to RHOAI's shared MLflow instance using standard OpenShift authentication and TLS. A multi-turn coding task with 8 model calls and 8 tool executions produced a 19-span trace with full tool names, latencies, request/response sizes, and context window stats — all visible in the MLflow UI.

For background on how RHOAI MLflow handles TLS and RBAC, see [MLflow on OpenShift: Authentication and TLS](../../../../docs/mlflow-openshift-auth-and-tls.md). This document covers the OpenClaw-specific OTel collector integration.

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│  OpenClaw Pod (YOUR-NAMESPACE)                              │
│                                                             │
│  ┌──────────────┐    OTLP/HTTP     ┌────────────────────┐  │
│  │              │  localhost:4318   │                    │  │
│  │   OpenClaw   │ ───────────────► │   OTel Collector   │  │
│  │   Gateway    │                  │   (sidecar)        │  │
│  │              │                  │                    │  │
│  └──────────────┘                  └─────────┬──────────┘  │
│                                              │              │
└──────────────────────────────────────────────┼──────────────┘
                                               │ OTLP/HTTP + bearer auth
                                               │ TLS (Service CA)
                                               ▼
                              ┌──────────────────────────────┐
                              │  RHOAI MLflow                │
                              │  (redhat-ods-applications)   │
                              │  port 8443, TLS              │
                              └──────────────────────────────┘
```

The collector runs as a sidecar in the OpenClaw pod, receiving spans on localhost and forwarding to RHOAI's shared MLflow over the cluster network. Authentication uses the pod's ServiceAccount token as a bearer token — the same RBAC mechanism described in the [shared guide](../../../../docs/mlflow-openshift-auth-and-tls.md#rbac-setup).

### Component versions

| Component | Image |
|---|---|
| OpenClaw (2026.9.8) | `ghcr.io/openclaw/openclaw@sha256:d0ded1dd76939b2bf4d67ef2d13247b8b160aa5666331d4a0b0e58811182cbb8` |
| OTel Collector (0.120.0) | `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib@sha256:85ac41c2db88d0df9bd6145e608a3cb023f5d8443868adbfbbf66efb51087917` |
| MLflow | RHOAI-managed (3.x) |

### RBAC and TLS

The overlay's [`rbac.yaml`](../overlays/mlflow-tracing/rbac.yaml) creates:

- A dedicated `openclaw-tracing` **ServiceAccount** for the OpenClaw pod
- A **RoleBinding** to the operator-provided `mlflow-integration` ClusterRole (see [RBAC Setup](../../../../docs/mlflow-openshift-auth-and-tls.md#rbac-setup) for details)

The OTel collector reads the SA token from `/var/run/secrets/kubernetes.io/serviceaccount/token` via its `bearertokenauth` extension and sends it as a bearer token with every request.

For TLS, it uses the service CA certificate at `/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`, which OpenShift auto-mounts into every pod. This is the same auth and TLS that the MLflow Python SDK handles via `MLFLOW_TRACKING_AUTH` and `MLFLOW_TRACKING_SERVER_CERT_PATH` — but since the OTel collector is not an MLflow SDK client, it's configured directly in the collector's [`config.yaml`](../overlays/mlflow-tracing/otel-collector-config.yaml).

---

## Trace Schema

### Span types

| Span name | What it captures | Key attributes |
|---|---|---|
| `openclaw.message.processed` | Turn-level root span | `channel`, `outcome`, `source` |
| `openclaw.harness.run` | Harness coordination | `items.started`, `items.completed`, `items.active` |
| `openclaw.run` | Agent run lifecycle | `provider`, `model`, `channel`, `trigger`, `outcome` |
| `openclaw.context.assembled` | Context window stats | `token_budget`, `system_prompt_chars`, `message_count`, `history_text_chars` |
| `openclaw.model.call` | LLM inference (span type: LLM) | `time_to_first_byte_ms`, `request_bytes`, `response_bytes`, `gen_ai.request.model` |
| `openclaw.tool.execution` | Tool call | `gen_ai.tool.name`, `openclaw.toolName`, `openclaw.tool.source`, `openclaw.errorCategory` |
| `openclaw.diagnostic.phase` | Startup diagnostics | `phase`, `cpu_user_ms`, `cpu_system_ms` |

### Trace hierarchy

A multi-tool agent turn produces this span tree:

```text
openclaw.message.processed           (turn-level root, 14.6s)
└── openclaw.harness.run             (items.completed=13)
    └── openclaw.run                 (trigger=user, outcome=completed)
        ├── openclaw.context.assembled    (token_budget=32768, message_count=4)
        ├── openclaw.model.call           (1.9s, request=68KB, TTFB=49ms)
        ├── openclaw.tool.execution       (read, 4ms)
        ├── openclaw.model.call           (2.0s, request=70KB, TTFB=294ms)
        ├── openclaw.tool.execution       (apply_patch, error)
        ├── openclaw.model.call           (1.4s, request=71KB, TTFB=43ms)
        ├── openclaw.tool.execution       (apply_patch, error)
        ├── ...                           (retry loop)
        ├── openclaw.tool.execution       (apply_patch, 15ms, success)
        └── openclaw.model.call           (1.8s, request=75KB, TTFB=48ms)
```

### Prototype trace data

> The example traces and screenshots below are from an earlier prototype run (vLLM `gpt-oss-120b`), not the 2026-10-08 `Qwen2.5-0.5B-Instruct` test named at the top of this document. They illustrate span shape and attributes; the exact counts, durations, and model name differ from the current setup.

**Cluster:** ROSA `agentic-mcp` | **Namespace:** `opc-on-ocp` | **Model:** `vllm/gpt-oss-120b`

| Trace | Spans | Duration | Description |
|---|---|---|---|
| `tr-55c54bab...` | 19 | 14.6s | Multi-tool: 8 model calls + 1 read + 7 apply_patch (6 errors, 1 success) |
| `tr-96ebd4a4...` | 5 | 5.0s | Single model call (4.7s LLM, 67KB request, 2.4KB response) |
| `tr-682e2d11...` | 5 | 3.1s | New session: first turn (1.6s LLM, 67KB request, 548B response) |

The `openclaw.model.call` spans capture `time_to_first_byte_ms` (40–294ms), `request_bytes` (67–75KB), and `response_bytes` (548B–2.4KB). Tool execution spans include `gen_ai.tool.name` and `openclaw.errorCategory` on failures.

### MLflow UI

**Traces list** — 74 traces captured in the `openclaw-tracing` experiment:

![MLflow traces list showing captured traces in the openclaw-tracing experiment](images/traces-list.png)

**Span waterfall** — tree hierarchy for a multi-tool agent turn:

![Span waterfall showing tree hierarchy for a multi-tool agent turn](images/span-waterfall.png)

**Model call attributes** — `openclaw.model.call` span detail showing request/response sizes and TTFB:

![Model call span details showing request/response sizes and TTFB](images/span-details.png)

**Tool execution attributes** — `openclaw.tool.execution` span detail showing tool name and source:

![Tool execution span details showing tool name and source](images/tool-execution-details.png)

---

## Setup

### Prerequisites

- **RHOAI with MLflow** — the `mlflow` service must be running in `redhat-ods-applications` with `--enable-workspaces`
- **The `mlflow-integration` ClusterRole** — shipped by the MLflow operator. Run `oc get clusterroles | grep mlflow-integration` to find the exact name (it may be prefixed, e.g. `mlflow-operator-mlflow-integration`). See [RBAC Setup](../../../../docs/mlflow-openshift-auth-and-tls.md#rbac-setup). RHOAI 3.3.1 does not ship this role; create it from the definition in [RBAC Setup](../../../../docs/mlflow-openshift-auth-and-tls.md#rbac-setup).
- **OpenShift 4.17+** with namespace-scoped access (`oc login`)
- **A vLLM-compatible model endpoint** (see [model-compatibility.md](model-compatibility.md))

### Step 1: Copy and configure the overlay

```bash
cp -r overlays/mlflow-tracing overlays/my-tracing
```

Replace every `YOUR-*` placeholder across these files:

| File | What to change |
|---|---|
| `kustomization.yaml` | `YOUR-NAMESPACE` |
| `rbac.yaml` | `YOUR-MLFLOW-INTEGRATION-CLUSTERROLE` (the name from the prerequisite step above) |
| `configmap-patch.yaml` | `YOUR-MODEL-ID`, `YOUR-VLLM-OR-OGX-ENDPOINT` |
| `otel-collector-config.yaml` | `YOUR-NAMESPACE` and `YOUR-EXPERIMENT-ID` (set after Step 3) |

Also set `VLLM_API_KEY` and `OPENCLAW_GATEWAY_TOKEN` in `../manifests/01-secret.yaml` — both default to placeholder values.

See [raw-deployment.md](raw-deployment.md) for how to find your model ID.

### Step 2: Create namespace and RBAC

```bash
oc new-project YOUR-NAMESPACE   # or use existing namespace

oc apply -f overlays/my-tracing/rbac.yaml -n YOUR-NAMESPACE
```

This creates:

- **`openclaw-tracing` ServiceAccount** — used by the OpenClaw pod
- **RoleBinding** — binds the `mlflow-integration` ClusterRole to the ServiceAccount

### Step 3: Create an MLflow experiment

RHOAI MLflow uses workspaces — your namespace maps to a workspace. Create an experiment in your workspace:

```bash
# RHOAI 3.3.1 exposes MLflow through an HTTPRoute on the data-science-gateway, not a Route named "mlflow".
# An `oc get route mlflow` returns NotFound there; read the host from the HTTPRoute instead.
MLFLOW_ROUTE=$(oc get httproute mlflow -n redhat-ods-applications -o jsonpath='{.spec.hostnames[0]}')
TOKEN=$(oc create token openclaw-tracing -n YOUR-NAMESPACE)

curl -s -X POST "https://${MLFLOW_ROUTE}/mlflow/api/2.0/mlflow/experiments/create" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-MLFLOW-WORKSPACE: YOUR-NAMESPACE" \
  -d '{"name": "openclaw-tracing"}' | python3 -m json.tool
```

> **Note (RHOAI 3.3.1):** the `data-science-gateway` fronts MLflow with an OAuth proxy built for browser access, which turns programmatic bearer-token API calls away. If these `curl` commands are rejected at the gateway, create and look up the experiment from the MLflow UI instead (RHOAI dashboard), or run them from inside the cluster against the MLflow service.

Note the `experiment_id` from the response. If the experiment already exists, look it up:

```bash
curl -s "https://${MLFLOW_ROUTE}/mlflow/api/2.0/mlflow/experiments/get-by-name?experiment_name=openclaw-tracing" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-MLFLOW-WORKSPACE: YOUR-NAMESPACE" | python3 -m json.tool
```

Update `YOUR-EXPERIMENT-ID` in your overlay's `otel-collector-config.yaml`.

### Step 4: Deploy OpenClaw

```bash
oc apply -k overlays/my-tracing
```

Wait for the `openclaw` pod to reach `2/2 Running` (gateway + otel-collector sidecar).

If OpenClaw already runs in this namespace, its init container keeps the existing `openclaw.json` on the PVC, so the overlay's config does not take effect by itself. Patch it into the running config and restart the gateway:

```bash
yq '.data["openclaw.json"]' overlays/my-tracing/configmap-patch.yaml | \
  oc exec -i deployment/openclaw -c gateway -n YOUR-NAMESPACE -- \
  node /app/dist/index.js config patch --stdin
oc rollout restart deployment/openclaw -n YOUR-NAMESPACE
```

> **Note:** patching the whole overlay config replaces the existing model settings, and OpenClaw refuses the patch when it would drop a provider's existing model entries (for example a different model ID). Preview the change first by adding `--dry-run` (`config patch --stdin --dry-run`) to see what would be written, and reconcile any model-ID differences before patching for real.

> **Note:** the overlay's `plugins.allow` is an exclusive allowlist (`["diagnostics-otel"]`), so applying it disables the other bundled plugins, including `device-pair`. The gateway doctor then warns that node onboarding join codes and `openclaw connect` are unavailable. Control UI login and device pairing still work. To keep a bundled plugin, add it to the `allow` list in your overlay's `configmap-patch.yaml`.

### Step 5: Connect

Port-forward OpenClaw:

```bash
oc port-forward deploy/openclaw 18789:18789 &
```

- **OpenClaw Control UI:** <http://localhost:18789> — paste the gateway token from `01-secret.yaml` when prompted
- **MLflow UI:** Access via the RHOAI dashboard. On RHOAI 3.3.1 there is no Route named `mlflow`; read the host from the HTTPRoute with `oc get httproute mlflow -n redhat-ods-applications -o jsonpath='{.spec.hostnames[0]}'`

Navigate to the `openclaw-tracing` experiment in your workspace to view traces.

> To use the Route instead of a port-forward, see [Access the Control UI](raw-deployment.md#through-the-route).

---

## Known Issues

### Traces not appearing (experiment 404)

**Symptom:** The OTel collector logs `Exporting failed. Dropping data. ... HTTP Status Code 404` but no further detail.

**Root cause:** The experiment ID in `otel-collector-config.yaml` doesn't exist in the target workspace. MLflow returns a 404 with no body, and the collector only logs the status code.

**Fix:** Verify the experiment exists in your workspace. Use the `get-by-name` API from Step 3 to look up the correct ID. Each workspace has its own experiment ID sequence — an experiment that exists in one workspace may not exist in another.

### Collector logs "error parsing protobuf response"

**Symptom:** The OTel collector logs `Exporting failed. Dropping data. ... error parsing protobuf response: unexpected EOF` for every batch.

**Cause:** MLflow accepts the traces but answers the protobuf request with a JSON body, which the collector cannot parse. The collector retries the batch and then logs it as dropped, but the traces are stored, each once. Check the MLflow log for `POST /v1/traces HTTP/1.1" 200 OK`.

### Traces rejected with HTTP 400 ("Invalid OpenTelemetry protobuf format")

**Cause:** MLflow's `/v1/traces` endpoint does not accept gzip-compressed requests, and gzip is the default of the collector's `otlphttp` exporter.

**Fix:** Keep `compression: none` on the `otlphttp` exporter in `otel-collector-config.yaml`, as the overlay does.

### Control UI fails through the Route

**Symptom:** The Route answers with HTTP 403 (`proxy_attribution_required`), or the Control UI reports `origin not allowed` and keeps reconnecting.

**Fix:** Use the Route annotation from the current manifests and add the Route to the allowed origins, as described in [Access the Control UI](raw-deployment.md#through-the-route). A port-forward works without either change.

---

## Gaps

1. **No tool call parameters or results in spans.** `openclaw.tool.execution` captures tool name, source, and latency, but not the input parameters or return values. Tracing what a tool was asked to do and what it returned requires cross-referencing session trajectory files.

2. **Token usage attributes.** OpenClaw 2026.9.8 emits usage attributes: `gen_ai.usage.*` on `openclaw.model.call`, plus an `openclaw.model.usage` span carrying `openclaw.tokens.*` (input, output, cache_read, cache_write, total), which align with the [OTel Semantic Conventions for GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) and enable cost tracking. These are populated when the provider result carries usage; we have not verified them live against vLLM responses in this setup.

3. **No session ID across traces.** Multi-turn conversations produce separate traces per turn with no shared identifier. Correlating turns into a conversation requires manual timestamp matching in the MLflow UI.

4. **Restart signal and exporter reload.** In OpenClaw 2026.9.8, `SIGUSR1` starts Node's inspector and no longer restarts the gateway; the service-aware restart signal is `SIGUSR2` (prefer `openclaw gateway restart`). Changes to `diagnostics.otel` hot-reload only the exporter service: the previous generation flushes and unsubscribes before the replacement starts, so an in-process restart no longer silently loses tracing. This overlay still sets the API key via env var interpolation instead of `paste-api-key`, which keeps the config stable across restarts.

---

## References

| Resource | URL |
|---|---|
| MLflow on OpenShift: Auth and TLS | [docs/mlflow-openshift-auth-and-tls.md](../../../../docs/mlflow-openshift-auth-and-tls.md) |
| OpenClaw OTel Documentation | <https://docs.openclaw.ai/gateway/opentelemetry> |
| OpenClaw Deployment Guide | [raw-deployment.md](raw-deployment.md) |
| OTel Collector Contrib | <https://github.com/open-telemetry/opentelemetry-collector-contrib> |
| MLflow OTLP Tracing | <https://mlflow.org/docs/latest/tracing/index.html> |
| OpenShift Service CA Certificates | <https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/security_and_compliance/configuring-certificates> |
