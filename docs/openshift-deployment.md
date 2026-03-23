# Deploying Agents to Red Hat OpenShift

This guide covers deploying any agent from this repository to an OpenShift cluster using Helm.

## Prerequisites

- [oc CLI](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) installed
- [Helm 3](https://helm.sh/docs/intro/install/) installed
- [Podman](https://podman.io/) installed (recommended) or Docker — only needed for Option A below
- Access to a container registry (e.g., Quay.io) — only needed for Option A below
- An OpenShift cluster with permissions to create Deployments, Services, and Routes

## Steps

### 1. Login to OpenShift and Container Registry

```bash
oc login -u <username> -p <password> https://<cluster-api-url>
```

If using Option A (local build + push), also log in to your container registry:

```bash
# Quay.io
podman login quay.io

# Docker Hub
podman login docker.io

# OpenShift internal registry
podman login $(oc get route default-route -n openshift-image-registry -o jsonpath='{.spec.host}')
```

### 2. Choose an Agent

Navigate to the agent you want to deploy:

```bash
cd agents/langgraph/react_agent   # or any other agent
```

### 3. Configure Environment

```bash
make init        # creates .env from .env.example
```
Edit `.env`:

```
API_KEY=dummy
BASE_URL=http://localhost:8321/v1
MODEL_ID=llama3.2:3b
```

### 4. Build the Container Image

#### Option A: Build locally and push to a registry

Requires Podman (or Docker) and a registry account (e.g., Quay.io).

```bash
make build    # builds the image locally
make push     # pushes to the registry specified in CONTAINER_IMAGE
```

The Makefile auto-detects Podman or Docker (preferring Podman).

#### Option B: Build in-cluster via OpenShift BuildConfig

No Podman, Docker, or registry account needed — just the `oc` CLI.

```bash
make build-openshift
```

This creates a BuildConfig (if it doesn't exist) and uploads your local source to OpenShift, which builds the image in-cluster using its internal registry.

After the build completes, set `CONTAINER_IMAGE` in your `.env` to the internal registry URL:

```
CONTAINER_IMAGE=image-registry.openshift-image-registry.svc:5000/<namespace>/<agent-name>:latest
```

Replace `<namespace>` with your OpenShift project name (run `oc project -q` to check).

### 5. Preview Rendered Manifests (optional)

Before deploying, you can inspect exactly what Kubernetes resources will be created:

```bash
make dry-run
```

Secrets are redacted in the output.

### 6. Deploy with Helm

```bash
make deploy
```

Under the hood this runs:

```bash
helm upgrade --install <agent-name> ../../charts/agent \
  -f values.yaml \
  --set secrets.apiKey="$API_KEY" \
  --set image.repository="$CONTAINER_IMAGE" \
  --set env.BASE_URL="$BASE_URL" \
  --set env.MODEL_ID="$MODEL_ID"
```

If any required environment variables are missing, `make deploy` will fail with a clear error listing which variables need to be set.

### 7. Verify

```bash
oc get pods -l app=<agent-name>
oc get route <agent-name>
```

The route URL is your agent's public endpoint.

### 8. Remove

```bash
make undeploy
```

## Customizing Deployment

Each agent has a `values.yaml` that overrides the shared chart defaults at `charts/agent/values.yaml`. You can:

- **Change resources**: edit `resources.requests` / `resources.limits` in the agent's `values.yaml`
- **Disable OpenShift Route** and use K8s Ingress instead:
  ```bash
  helm upgrade --install <agent-name> ../../charts/agent \
    -f values.yaml \
    --set openshift.route.enabled=false \
    --set ingress.enabled=true \
    --set ingress.host=my-agent.example.com
  ```
- **Add environment variables**: add entries to `env:` in the agent's `values.yaml`
- **Add volumes**: add entries to `volumes:` and `volumeMounts:` (see the agentic_rag agent for an example)

## Shared Helm Chart

All agents share a single Helm chart at `charts/agent/`. The override chain is:

```
charts/agent/values.yaml        <-- global defaults
  agents/.../values.yaml        <-- agent-specific overrides
    --set flags                 <-- CLI overrides at deploy time
```
