# Guardrails tracing

NeMo Guardrails supports [OpenTelemetry tracing](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/latest/html/enabling_ai_safety_with_guardrails/enabling-ai-safety-with-nemo-guardrails_nemo-guardrails#configuring-observability-for-nemo-guardrails-with-opentelemetry_nemo-guardrails)
(RHOAI 3.4+). When enabled, the proxy emits per-rail span data — request flow,
LLM latency, and each rail's execution time — as OpenTelemetry traces.

This directory documents every way to collect those spans:

| Path | Backend | Storage | Metrics | Use for |
|------|---------|---------|---------|---------|
| [Local](#local-otel-collector--jaeger--prometheus) | OTel Collector + Jaeger + Prometheus (compose) | in-memory | ✅ RED metrics | development on your laptop |
| [Cluster — demo](#cluster-demo-tempomonolithic) | `TempoMonolithic` | in-memory (ephemeral) | ❌ traces only | a 5-minute tutorial on a cluster |
| [Cluster — production](#cluster-production-tempostack) | `TempoStack` (+ optional Collector) | object storage (S3/MinIO/ODF) | optional (Collector) | anything durable/supported |

**Tracing is opt-in.** It is off by default and adds zero overhead when unset.
The `tracing:` block in `config.yaml.example` ships with `enabled: false`;
`generate_config.py` flips it to `true` only when `GUARDRAILS_TRACING_ENABLED=true`,
so the server command is byte-identical when tracing is off. Content capture stays
`false` in every mode, so blocked prompts and outputs are never echoed into span
attributes.

> **Why a wrapper is needed locally but not on cluster:** NeMo's
> `OpenTelemetryAdapter` uses only the OTel *API* — it never configures an SDK.
> Locally the Makefile launches the server under
> [`opentelemetry-instrument`](https://opentelemetry.io/docs/zero-code/python/)
> (from `opentelemetry-distro`), which reads the standard `OTEL_*` env vars and
> wires up the `TracerProvider`/exporter before NeMo initializes. On RHOAI the
> operator's guardrails container configures the SDK itself from the `OTEL_*`
> env vars, so no wrapper is involved.

Manifests in this directory:

- [`tempo-monolithic-demo.yaml`](tempo-monolithic-demo.yaml) — the demo cluster backend.
- [`tempo-stack-production.yaml`](tempo-stack-production.yaml) — the production cluster backend.
- [`object-storage-secret.example.yaml`](object-storage-secret.example.yaml) — credentials template for the production backend.
- [`otel-collector-spanmetrics.yaml`](otel-collector-spanmetrics.yaml) — optional per-rail metrics on cluster.

---

## Local: OTel Collector + Jaeger + Prometheus

A ready-made compose stack lives in [`../../guardrails/tracing/`](../../guardrails/tracing/):

```text
agent → guardrails proxy (opentelemetry-instrument) → OTel Collector
          ├─ Jaeger      (per-rail traces, UI :16686)
          └─ Prometheus  (spanmetrics RED metrics, UI :9090)
```

1. **Start the stack** (needs `podman-compose` or Docker's compose plugin):

   ```bash
   make guardrails-tracing-up
   ```

   This brings up the Collector (OTLP on `:4317`/`:4318`), Jaeger
   (`http://localhost:16686`), and Prometheus (`http://localhost:9090`).

2. **Start the proxy with tracing on** — set these in `.env` (or export them
   inline), then run the server:

   ```ini
   GUARDRAILS_TRACING_ENABLED=true
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
   OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
   OTEL_SERVICE_NAME=nemo-guardrails
   ```

   ```bash
   make guardrails-server-local      # or guardrails-server-nemoguard
   ```

3. **Send traffic** (`make run-app` then chat with the agent, or hit the proxy
   directly), then open the UIs.

4. **Tear down** when finished:

   ```bash
   make guardrails-tracing-down
   ```

> This local stack is for development only — no auth, no TLS. For a cluster, use
> the Tempo paths below.

---

## Cluster: demo (`TempoMonolithic`)

The quick path for a tutorial cluster: a single `TempoMonolithic` with in-memory
storage and the Jaeger UI enabled — no object storage, no separate Collector CR.
In-cluster, the guardrails proxy exports over gRPC to Tempo (no
`opentelemetry-instrument` wrapper — the RHOAI container configures the SDK itself).

1. **Install the Tempo Operator** — subscribe to `tempo-product` from
   OperatorHub. The operator is only the controller; you still deploy a Tempo
   instance (step 2).

2. **Deploy the demo Tempo instance** in your namespace (e.g. `ci-testing`):

   ```bash
   oc apply -n ci-testing -f deploy/tracing/tempo-monolithic-demo.yaml
   ```

   It creates Service `tempo-guardrails-tracing` (OTLP gRPC :4317, HTTP :4318)
   and route `tempo-guardrails-tracing-jaegerui`. The operator will warn that a
   non-multitenant `TempoMonolithic` is *not supported on OpenShift* and its
   in-memory storage is ephemeral (traces are lost on pod restart) — both
   expected for a short-lived tutorial. For durability, use the production path.

3. **Point `cluster.env` at that instance's OTLP service:**

   ```ini
   GUARDRAILS_TRACING_ENABLED=true
   OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo-guardrails-tracing.ci-testing.svc.cluster.local:4317
   OTEL_SERVICE_NAME=nemo-guardrails
   OTEL_EXPORTER_OTLP_PROTOCOL=grpc
   OTEL_METRICS_EXPORTER=none
   ```

4. **Deploy** (`make deploy-guardrails`) — the tracing block is rendered into the
   ConfigMap and the `OTEL_*` vars onto the `NemoGuardrails` CR automatically.

5. **Access traces** via the Jaeger UI route
   (`oc get route -n <ns> | grep jaegerui`) or port-forward
   (`oc port-forward svc/tempo-guardrails-tracing-jaegerui 16686:16686`), then
   pick service `nemo-guardrails`. See [Reading a trace](#reading-a-trace).

---

## Cluster: production (`TempoStack`)

`TempoStack` persists traces to object storage and is the supported,
multi-tenant-capable backend for OpenShift. Use it for anything beyond a
tutorial. It cannot be a pure copy-paste apply: you must provide an object
storage bucket (AWS S3, MinIO, or ODF) and its credentials.

1. **Install the Tempo Operator** — subscribe to `tempo-product` from OperatorHub
   (same as the demo path).

2. **Provision object storage** — an S3/MinIO/ODF bucket the cluster can reach.

3. **Create the credentials Secret** from the template, then apply it *before*
   the TempoStack CR:

   ```bash
   cp deploy/tracing/object-storage-secret.example.yaml \
      deploy/tracing/object-storage-secret.yaml
   # edit object-storage-secret.yaml: endpoint, bucket, region, access keys
   oc apply -n ci-testing -f deploy/tracing/object-storage-secret.yaml
   ```

   Never commit the filled-in copy — `object-storage-secret.yaml` is gitignored.

4. **Deploy the TempoStack:**

   ```bash
   oc apply -n ci-testing -f deploy/tracing/tempo-stack-production.yaml
   ```

   The ingest endpoint is now the **distributor** service, not a monolithic one:
   `tempo-guardrails-tracing-distributor.ci-testing.svc.cluster.local:4317`. The
   Jaeger UI is exposed via the `tempo-guardrails-tracing-query-frontend` route.

5. **Choose traces-only or traces+metrics**, then set `cluster.env`:

   - **Traces only** — point straight at the distributor:

     ```ini
     GUARDRAILS_TRACING_ENABLED=true
     OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo-guardrails-tracing-distributor.ci-testing.svc.cluster.local:4317
     OTEL_SERVICE_NAME=nemo-guardrails
     OTEL_EXPORTER_OTLP_PROTOCOL=grpc
     OTEL_METRICS_EXPORTER=none
     ```

   - **Traces + per-rail metrics** — deploy the spanmetrics Collector and point
     at it instead (see [Metrics on cluster](#metrics-on-cluster) below).

6. **Deploy** (`make deploy-guardrails`), send traffic, and read traces exactly
   as in the demo path.

---

## Reading a trace

In **Jaeger**, pick service `nemo-guardrails` and search. Each request is one trace:

- The **root span** covers the whole guardrails request.
- **Rail spans** are the children. NeMo emits *every* rail under the same span
  name (`guardrails.rail`); the specific rail is identified by the `rail.name`
  (e.g. `self_check_input`, `topic_safety_check_input`) and `rail.type`
  (`input` / `output` / `dialog` / `generation`) attributes.
- **`gen_ai.*` spans** capture the underlying LLM calls and their latency.

Because content capture is disabled, spans carry timing and rail metadata only —
not the user's text or model output. With the nemoguard profile you'll also see
`content_safety_check_input`/`output` and `topic_safety_check_input` rails.

---

## Metrics on cluster

The Tempo paths ship **traces only** — the Prometheus RED metrics from the local
stack are not part of them (`OTEL_METRICS_EXPORTER=none`). On OpenShift, per-rail
metrics come from an `OpenTelemetryCollector` (Red Hat build of OpenTelemetry)
whose [spanmetrics connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/spanmetricsconnector)
derives them and exposes them for scraping by
[user workload monitoring](https://docs.openshift.com/container-platform/latest/observability/monitoring/enabling-monitoring-for-user-defined-projects.html)
(UWM). The stock OpenShift Prometheus (`openshift-monitoring`) collects platform
metrics only and won't scrape app spans on its own.

To enable the metrics path:

1. Install the **Red Hat build of OpenTelemetry** operator and ensure **UWM is
   enabled** (the `openshift-user-workload-monitoring` namespace has running pods).

2. Apply the Collector, which forwards traces to Tempo *and* exposes spanmetrics:

   ```bash
   oc apply -n ci-testing -f deploy/tracing/otel-collector-spanmetrics.yaml
   ```

3. Point `cluster.env` at the Collector instead of Tempo directly:

   ```ini
   OTEL_EXPORTER_OTLP_ENDPOINT=http://guardrails-spanmetrics-collector.ci-testing.svc.cluster.local:4317
   OTEL_METRICS_EXPORTER=none
   ```

4. Query in the OpenShift console (**Observe → Metrics**) — the metric labels
   `rail_name` / `rail_type` come from the span attributes (dots become
   underscores):

   ```promql
   # Calls per rail
   sum by (rail_name, rail_type) (traces_span_metrics_calls_total{span_name="guardrails.rail"})

   # p95 latency per rail
   histogram_quantile(0.95, sum by (le, rail_name) (rate(traces_span_metrics_duration_milliseconds_bucket{span_name="guardrails.rail"}[5m])))
   ```

The same PromQL works against the local Prometheus (`http://localhost:9090`),
which the compose stack's Collector feeds directly; see
[`../../guardrails/tracing/otel-collector-config.yaml`](../../guardrails/tracing/otel-collector-config.yaml).

---

See [`../overlays/ci-testing/cluster.env.example`](../overlays/ci-testing/cluster.env.example)
for the full set of cluster-side variables.
