# MLflow Tracing Setup for OpenCode on RHOAI

Enable MLflow tracing for OpenCode on Red Hat OpenShift AI. Works in both web and CLI modes.

For trace schema, backend comparisons, and latency benchmarks, see [mlflow-tracing.md](mlflow-tracing.md).

## Prerequisites

- OpenCode deployment manifests from [aicatalyst-team/opencode-openshift](https://github.com/aicatalyst-team/opencode-openshift)
- MLflow instance running on your RHOAI cluster with a workspace matching your namespace

## Setup

### 1. Build the image

Follow the [aicatalyst-team/opencode-openshift](https://github.com/aicatalyst-team/opencode-openshift) deployment guide, but use [`Containerfile.mlflow`](../Containerfile.mlflow) instead of the base Containerfile. It extends the base OpenCode image with `mlflow[kubernetes]` and the pre-built `@mlflow/opencode` plugin.

### 2. Grant RBAC

Grant the `edit` role to the service account used by the deployment. Check your deployment's `serviceAccountName` — it may be `default` or a named account like `opencode-web`:

```bash
oc adm policy add-role-to-user edit -z <service-account-name> -n <your-namespace>
```

### 3. Configure MLflow env vars

Find your MLflow tracking URI:

```bash
oc get svc -A | grep mlflow
# Use the service name, namespace, and port to construct:
# https://<service-name>.<namespace>.svc:<port>/mlflow
```

Set these env vars on the deployment:

| Env var | What to set |
|---|---|
| `MLFLOW_TRACKING_URI` | The URI from the command above |
| `MLFLOW_WORKSPACE` | Your namespace / project name |
| `MLFLOW_EXPERIMENT_NAME` | Name for your experiment (e.g., `opencode-traces`) |
| `MLFLOW_TRACKING_INSECURE_TLS` | `true` for dev/test, remove for production with proper TLS |
| `NODE_TLS_REJECT_UNAUTHORIZED` | `0` for dev/test, remove for production with proper TLS |
| `OPENCODE_MODE` | `web` (default) or `cli` for terminal mode |

### 4. Deploy

**If deploying for the first time:** Add the env vars above and the MLflow entrypoint block from [`entrypoint-patch.yaml`](../overlays/mlflow-tracing/entrypoint-patch.yaml) to your deployment manifests before applying.

**If OpenCode is already deployed:** Make sure the deployment is using the image built from [`Containerfile.mlflow`](../Containerfile.mlflow). Then clone the [opencode-openshift](https://github.com/aicatalyst-team/opencode-openshift) repo and apply the [`overlays/mlflow-tracing/`](../overlays/mlflow-tracing/) kustomize overlay:

```bash
# Clone the base manifests (if not already cloned)
git clone https://github.com/aicatalyst-team/opencode-openshift.git

# Edit kustomization.yaml — set namespace and adjust the manifests path
# Edit deployment-patch.yaml — set the env vars above
oc apply -k overlays/mlflow-tracing/
oc rollout restart deployment/<your-deployment-name>
```

## Verify

```bash
# Check startup logs
oc logs deployment/<your-deployment-name> | grep -i mlflow

# CLI mode
oc exec deployment/<your-deployment-name> -- bash -c '
  source $HOME/.mlflow-env 2>/dev/null
  cd /opt/app-root/workspace
  opencode run "What is 2+2?"
'

# Web mode: send a message in the browser, then check MLflow
```

## View traces

```bash
oc get consolelink mlflow -o jsonpath='{.spec.href}'
```

Navigate to your workspace and experiment name to see traces.

## Key notes

- The image must be built with [`Containerfile.mlflow`](../Containerfile.mlflow)
- `MLFLOW_TRACKING_TOKEN` is read from the pod's SA token automatically
- The entrypoint handles plugin install, experiment creation, and auth — no manual plugin setup needed
- Until the next `@mlflow/opencode` npm release includes the workspace header fix, the entrypoint replaces the cached plugin with a build from the v3.14.0 release tag

> **TLS note:** `NODE_TLS_REJECT_UNAUTHORIZED=0` disables TLS verification for all Node.js connections in the container, not just MLflow. For production, use `NODE_EXTRA_CA_CERTS` instead. Upstream work is in progress to support `MLFLOW_TRACKING_INSECURE_TLS` and `MLFLOW_TRACKING_SERVER_CERT_PATH` scoped to MLflow connections only ([mlflow#24140](https://github.com/mlflow/mlflow/issues/24140)). Kubernetes-native auth (`MLFLOW_TRACKING_AUTH`) is also being added to the TypeScript SDK ([mlflow#24141](https://github.com/mlflow/mlflow/issues/24141)).
