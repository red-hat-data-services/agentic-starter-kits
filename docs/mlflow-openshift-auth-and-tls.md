# MLflow on OpenShift: Authentication and TLS

MLflow on Red Hat OpenShift AI (RHOAI) enforces TLS and RBAC authentication. Any client that sends traces — the MLflow Python SDK, the TypeScript SDK, or a custom OTLP exporter like an OTel collector — needs to handle both.

This document covers the network paths client can route through, TLS setup, and RBAC configuration. The Python and TypeScript SDK sections show MLflow SDK-specific env vars (these should converge over time, but currently differ — see [TypeScript SDK: What's Different](#typescript-sdk-whats-different)). For other clients (e.g., OTel collectors), the same concepts apply through your client's own configuration.

RHOAI uses the [MLflow workspaces](https://mlflow.org/docs/latest/self-hosting/workspaces/) feature for multi-tenant isolation, where each Kubernetes namespace maps 1:1 to an MLflow workspace.

For how the Python agents in this repo set up MLflow tracing, see [tracing.md](../tracing.md). Non-Python agents (e.g., claude-code, openclaw) have their own tracing docs in their respective directories.

---

## Table of Contents

- [Two Network Paths to MLflow Server](#two-network-paths-to-mlflow-server)
- [TLS Configuration](#tls-configuration)
- [RBAC Setup](#rbac-setup)
- [Authentication](#authentication)
- [Complete .env Examples](#complete-env-examples)
- [TypeScript SDK: What's Different](#typescript-sdk-whats-different)
- [Agent Implementations](#agent-implementations)

---

## Two Network Paths to MLflow Server

| | External route | Internal service |
|---|---|---|
| **URL pattern** | `https://mlflow-<ns>.apps.<cluster>/mlflow` | `https://mlflow.<ns>.svc:8443/mlflow` |
| **TLS terminated by** | OpenShift router (re-encrypts to pod) | MLflow pod directly |
| **Certificate signed by** | Cluster-dependent (public CA on ROSA, may be custom CA on other clusters) | [OpenShift service CA](https://docs.openshift.com/container-platform/4.17/security/certificates/service-serving-certificate.html) (cluster-internal) |
| **System CA bundle covers it?** | Depends on cluster — check with your admin | No — requires the service CA cert at `/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt` |
| **When to use** | Local dev (workstation to cluster) | In-pod (faster, no router hop) |

The internal service URL uses a certificate signed by the OpenShift service CA — a cluster-internal CA that is not in the pod's system CA bundle. Every pod gets this CA cert auto-mounted at `/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`. Point your client to this file for TLS verification (see [TLS Configuration](#tls-configuration) below).

---

## TLS Configuration

### 1. System CAs (default — external route)

When the external route's certificate is signed by a public CA (e.g., Let's Encrypt), no TLS configuration is needed — the public CA is already in the system CA bundle, so `verify=True` (the default) works.

```ini
# External route — no TLS config needed when the route cert is signed by a public CA
MLFLOW_TRACKING_URI=https://mlflow-redhat-ods-applications.apps.<cluster>/mlflow
```

> **Note:** If your cluster's route certificate is signed by a custom or internal CA, you will need to configure `MLFLOW_TRACKING_SERVER_CERT_PATH` with that CA file — the same approach as for the internal service (see below).

### 2. Custom CA certificate (internal service or custom route CA)

When the server certificate is signed by a CA that is not in the system CA bundle, point the mlflow SDK (only supported in python for now) to the CA file:

```ini
MLFLOW_TRACKING_SERVER_CERT_PATH=/path/to/ca-cert.crt
```

**Internal service (OpenShift service CA):** The most common case. Every pod gets the service CA at a well-known path:

```ini
MLFLOW_TRACKING_URI=https://mlflow.redhat-ods-applications.svc:8443/mlflow
MLFLOW_TRACKING_SERVER_CERT_PATH=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
```

**External route with custom CA:** If your cluster's route certificate is signed by a non-public CA, mount that CA file into your pod and point to it:

```ini
MLFLOW_TRACKING_URI=https://mlflow-redhat-ods-applications.apps.<cluster>/mlflow
MLFLOW_TRACKING_SERVER_CERT_PATH=/path/to/your-custom-ca.crt
```

### 3. Insecure (development only — not recommended)

Disables all certificate verification for MLflow connections.

```ini
MLFLOW_TRACKING_INSECURE_TLS=true
```

---

## RBAC Setup

MLflow uses Kubernetes RBAC with pseudo-resources in the `mlflow.kubeflow.org` API group. These are not real Kubernetes CRDs — they exist solely for the RBAC policy engine.

**How it works** : the tracing client sends a bearer token with every request. The MLflow server forwards that token to the Kubernetes API ("can this identity do X in namespace Y?"). Kubernetes checks the role bindings and returns allow or deny.

If you don't have a namespace yet, create one — it becomes your MLflow workspace:

```bash
oc new-project my-namespace
```

### The `mlflow-integration` ClusterRole

The operator ships a built-in ClusterRole with the permissions needed for typical agent workloads (create experiments, log traces, register models). The exact name may be prefixed by the operator — find it with:

```bash
oc get clusterroles | grep mlflow-integration
# e.g. mlflow-operator-mlflow-integration
```

The role looks like:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: mlflow-integration
rules:
  - apiGroups: ["mlflow.kubeflow.org"]
    resources: ["datasets", "experiments", "registeredmodels"]
    verbs: ["get", "list", "create", "update"]
  - apiGroups: ["mlflow.kubeflow.org"]
    resources: ["gatewayendpoints"]
    verbs: ["get", "list"]
  - apiGroups: ["mlflow.kubeflow.org"]
    resources: ["gatewayendpoints/use"]
    verbs: ["create"]
```

### Binding the ClusterRole to a service account

Create a **RoleBinding** (namespace-scoped) to grant a service account access to a specific workspace:

```bash
# Use the actual ClusterRole name from the grep above
oc -n <namespace> create rolebinding <name>-mlflow-integration \
  --clusterrole=<mlflow-integration-clusterrole> \
  --serviceaccount=<namespace>:<service-account-name>
```

### Which service account?

Every pod uses the identity of a service account. If your deployment doesn't set `serviceAccountName`, it uses the namespace's `default` SA — this is the simplest option and works well when the namespace is dedicated to a single agent:

```bash
# Bind the mlflow-integration role to the default SA
oc -n <namespace> create rolebinding <namespace>-mlflow-integration \
  --clusterrole=<mlflow-integration-clusterrole> \
  --serviceaccount=<namespace>:default
```

If the namespace runs other pods that should not have MLflow access, create a dedicated service account:

```bash
oc -n <namespace> create sa <agent-name>-tracing

oc -n <namespace> create rolebinding <agent-name>-mlflow-integration \
  --clusterrole=<mlflow-integration-clusterrole> \
  --serviceaccount=<namespace>:<agent-name>-tracing
```

Then set `serviceAccountName: <agent-name>-tracing` in your deployment spec.

Create the RoleBinding before deploying or generating tokens — without it, MLflow returns 403. See [Authentication](#authentication) for how to generate and configure the token.

---

## Authentication

Every request to MLflow needs a bearer token — the same RBAC flow described above. This section covers how the client provides that token. Make sure the service account has the necessary role bindings first (see [RBAC Setup](#rbac-setup)).

### Authentication modes (Python SDK)

The following auth modes are supported by the MLflow **Python** SDK. For TypeScript SDK differences, see [TypeScript SDK: What's Different](#typescript-sdk-whats-different).

| Mode | Env vars | When to use | Python SDK version |
|---|---|---|---|
| Manual token | `MLFLOW_TRACKING_TOKEN`, `MLFLOW_WORKSPACE` | Local dev (workstation → cluster) | `mlflow>=3.6` |
| K8s service account | `MLFLOW_TRACKING_AUTH=kubernetes` or `kubernetes-namespaced` | In-pod (automatic SA token + namespace) | `mlflow>=3.11` |

### Manual token (local development)

For local development against a remote MLflow server, provide a token and workspace name:

```ini
MLFLOW_TRACKING_TOKEN=<token>
MLFLOW_WORKSPACE=<namespace>
```

**Best practice:** Use `oc create token <service-account-name>` rather than `oc whoami -t`:

| | `oc create token <sa>` | `oc whoami -t` |
|---|---|---|
| **Scope** | Bound to a specific service account | Your full user session |
| **Lifetime** | Short-lived (1 hour default, configurable by cluster admin) | Long-lived (session token) |
| **Permissions** | Only what the SA's RBAC grants | All your user permissions |
| **Recommended** | Yes | No |

Example (assumes the service account already has the `mlflow-integration` role binding):

```bash
# Create a short-lived token for the "default" SA in your namespace
export MLFLOW_TRACKING_TOKEN=$(oc create token default)
export MLFLOW_WORKSPACE=my-namespace
```

### Kubernetes service account auth (in-pod)

When running inside a pod, the MLflow Python SDK (`mlflow>=3.11`) can automatically read the service account token and namespace from the pod's filesystem — no manual token management needed.

```ini
MLFLOW_TRACKING_AUTH=kubernetes-namespaced
```

This reads:

- Token from `/var/run/secrets/kubernetes.io/serviceaccount/token`
- Namespace from `/var/run/secrets/kubernetes.io/serviceaccount/namespace`

No `MLFLOW_TRACKING_TOKEN` or `MLFLOW_WORKSPACE` needed.

Both `kubernetes` and `kubernetes-namespaced` values are supported. `kubernetes-namespaced` is the recommended value — it auto-detects the namespace, while `kubernetes` requires separate workspace configuration.

---

## Complete .env Examples

### Local development (client pings the external exposed route)

```ini
MLFLOW_TRACKING_URI=https://mlflow-redhat-ods-applications.apps.<cluster>/mlflow
MLFLOW_EXPERIMENT_NAME=my-experiment
MLFLOW_TRACKING_TOKEN=<paste token from: oc create token default>
MLFLOW_WORKSPACE=my-namespace
MLFLOW_HEALTH_CHECK_TIMEOUT=10
```

No TLS configuration needed — assumes the external route certificate is signed by a public CA (see [TLS Configuration](#tls-configuration) if yours is not).

### In-pod (client inside OpenShift pings the internal service URL of MLflow, MLflow 3.11+)

```ini
MLFLOW_TRACKING_URI=https://mlflow.redhat-ods-applications.svc:8443/mlflow
MLFLOW_EXPERIMENT_NAME=my-experiment
MLFLOW_TRACKING_AUTH=kubernetes-namespaced
MLFLOW_TRACKING_SERVER_CERT_PATH=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
```

Uses the internal service (faster, stays in cluster) with the OpenShift service CA for TLS verification.

---

## TypeScript SDK: What's Different

The authentication and TLS sections above describe the **Python SDK** behavior. The MLflow TypeScript SDK (`@mlflow/core`, used by agents like claude-code via the MLflow TS plugin) does not read several of these env vars. This section documents the gaps and workarounds for TS-based agents deployed on OpenShift.

| Feature | Python SDK (env var) | TS SDK support | Workaround for TS agents |
|---|---|---|---|
| K8s SA auth | `MLFLOW_TRACKING_AUTH=kubernetes-namespaced` | Not supported | Container entrypoint reads SA token from `/var/run/secrets/kubernetes.io/serviceaccount/token` and namespace from `.../namespace`, then exports `MLFLOW_TRACKING_TOKEN` and `MLFLOW_WORKSPACE` before launching the Node.js process |
| TLS cert config | `MLFLOW_TRACKING_SERVER_CERT_PATH` | Not supported | `NODE_EXTRA_CA_CERTS=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt` |
| Insecure TLS | `MLFLOW_TRACKING_INSECURE_TLS` | Not supported | `NODE_TLS_REJECT_UNAUTHORIZED=0` (process-wide — avoid in production) |

### `NODE_EXTRA_CA_CERTS` is additive

Unlike `NODE_TLS_REJECT_UNAUTHORIZED=0` (which disables **all** TLS verification for the entire Node.js process), `NODE_EXTRA_CA_CERTS` **adds** the specified CA to the default trust store alongside public CAs (Let's Encrypt, DigiCert, etc.). It does not replace them.
For time being, this is the recommended approach for TS agents connecting to the internal MLflow service.

### Example: TS agent env vars (in-pod, internal service)

```ini
MLFLOW_TRACKING_URI=https://mlflow.redhat-ods-applications.svc:8443/mlflow
MLFLOW_EXPERIMENT_NAME=my-experiment
MLFLOW_TRACKING_TOKEN=<injected by entrypoint>
MLFLOW_WORKSPACE=<injected by entrypoint>
NODE_EXTRA_CA_CERTS=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
```

---

## Agent Implementations

Different agents use different clients to send traces to MLflow — the auth and TLS concepts above apply to all of them:

- **react_agent** (MLflow Python SDK) — [tracing setup](../agents/langgraph/templates/react_agent/README.md#tracing-optional), reference implementation for Python framework agents
- **claude-code** (MLflow TS SDK + Python hook) — [tracing setup](../agents/claude-code/README.md#mlflow-tracing-optional)
- **openclaw** (OTel collector sidecar) — [tracing setup](../agents/openclaw/deployment/docs/mlflow-tracing.md)
