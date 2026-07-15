# OpenCode on Red Hat OpenShift AI

Deploy [OpenCode](https://opencode.ai), an open-source terminal-based coding agent, on Red Hat OpenShift AI. OpenCode provides AI-assisted code generation, code review, and multi-file editing capabilities, powered by models served on the platform through vLLM or OGX inference backends.

## Prerequisites

- OpenShift 4.17+ cluster with `oc` CLI authenticated
- A model serving endpoint (vLLM, KServe, RHOAI model serving, or OGX) exposing an OpenAI-compatible API on a cluster-internal Service
- Block storage class (gp3-csi, managed-csi, thin-csi) for the workspace PVC

## Quick start

The quick start deploys OpenCode in **web mode** using the pre-built container image with OAuth-secured browser access. No image build is required.

```bash
cd agents/opencode/deployment

# Edit manifests/kustomization.yaml — set BASE_URL, API_KEY, and MODEL_NAME
# (For production, use Sealed Secrets or External Secrets Operator instead of inline literals)
oc apply -k manifests/

oc -n opencode rollout status deployment/opencode-web
oc -n opencode get route opencode-web -o jsonpath='https://{.spec.host}{"\n"}'
```

Open the route URL in your browser. OpenShift OAuth handles authentication.

For **CLI mode** (headless, no OAuth, `oc exec` access):

```bash
cd agents/opencode/deployment

oc apply -k overlays/cli

oc -n opencode rollout status deployment/opencode-web
oc -n opencode exec -it deployment/opencode-web -c opencode-web -- opencode
```

See [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md) for custom environments, detailed configuration, architecture, and security.

## Container image and variants

The quick start uses a **pre-built image** — no Containerfile or image build is needed. The Containerfiles in this kit are for extended variants that add capabilities on top of the base image.

| Variant | Image / Containerfile | Use when | Build required? |
|---------|----------------------|----------|-----------------|
| **Base (quick start)** | `quay.io/opendatahub/odh-opencode-rhel9:20260619-194847e` | Standard web or CLI deployment | No — pre-built |
| **MLflow tracing** | [`Containerfile.mlflow`](deployment/Containerfile.mlflow) | You need agent execution traces exported to MLflow | Yes |
| **A2A / Kagenti** | [`Containerfile.a2a`](deployment/Containerfile.a2a) | You want Kagenti agent discovery via the A2A protocol (agent card and discovery available; task execution pending RHAIENG-5826) | Yes |
| **OpenShell sandbox** | [`Containerfile.openshell`](deployment/Containerfile.openshell) | Sandboxed experimentation inside an OpenShell gateway | Yes |

The base image is built from [opendatahub-io/opencode](https://github.com/opendatahub-io/opencode) (UBI 9 minimal, non-root, `restricted-v2` SCC). Each Containerfile extends this base with additional dependencies — they are separate because each variant has different runtime requirements and not all users need every capability.

### Building a variant

```bash
cd agents/opencode/deployment

# MLflow tracing
podman build --platform linux/amd64 -t opencode-mlflow:latest -f Containerfile.mlflow .

# A2A / Kagenti
podman build --platform linux/amd64 -t opencode-a2a:latest -f Containerfile.a2a .

# OpenShell sandbox
podman build --platform linux/amd64 -t opencode-sandbox:latest -f Containerfile.openshell .
```

## Deployment manifests (Kustomize)

All deployment modes use [Kustomize](https://kustomize.io/) with a shared base and per-mode overlays:

```text
deployment/manifests/          # Base: web mode with OAuth proxy
deployment/overlays/cli/       # Overlay: headless CLI mode (no OAuth, no Route)
deployment/overlays/example/   # Overlay: template for custom environments
deployment/overlays/mlflow-tracing/  # Overlay: MLflow tracing integration
```

Edit `manifests/kustomization.yaml` to configure the model endpoint, API key, model name, and storage class. Apply overlays with `oc apply -k overlays/<mode>`.

To use a lighter model for summarization, commit messages, and other quick tasks, set `SMALL_MODEL_NAME` in the deployment environment. If not set, it defaults to `MODEL_NAME`. Both models must be reachable through the configured provider endpoint.

## Extending OpenCode at startup

- **MCP servers** — Inject MCP server configuration at startup via ConfigMap (`opencode-web-mcp`), extending the agent with additional tools without rebuilding the image.
- **Skills** — Mount custom skills (project-specific instructions) via ConfigMap at startup. Skills are auto-discovered by the agent.

See [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md) for configuration details.

## Project structure

```text
agents/opencode/
├── deployment/
│   ├── manifests/                    # Base kustomize manifests (web mode + OAuth)
│   │   ├── kustomization.yaml        # Kustomize entrypoint
│   │   ├── namespace.yaml
│   │   ├── serviceaccount.yaml
│   │   ├── deployment.yaml           # Two-container pod (oauth-proxy + opencode)
│   │   ├── service.yaml
│   │   ├── route.yaml
│   │   ├── pvc.yaml
│   │   ├── entrypoint.sh             # Container entrypoint (config, MCP, mode switching)
│   │   └── config-template.json      # OpenCode provider config (vLLM + OGX)
│   ├── overlays/
│   │   ├── cli/                      # CLI mode overlay
│   │   ├── example/                  # Template for custom environments
│   │   └── mlflow-tracing/           # MLflow tracing overlay
│   ├── Containerfile.mlflow          # MLflow tracing image variant
│   ├── Containerfile.a2a             # A2A / Kagenti agent discovery variant
│   ├── Containerfile.openshell       # OpenShell sandbox variant
│   ├── entrypoint-a2a.sh             # Entrypoint for A2A variant
│   ├── kagenti-agent.yaml            # OpenShift Template for Kagenti deployment
│   ├── DEPLOYMENT.md                 # Full deployment guide (config, architecture, security)
│   ├── README.md                     # OpenShell sandbox guide
│   ├── README-a2a.md                 # A2A / Kagenti deployment guide
│   └── docs/                         # MLflow tracing documentation
└── README.md                         # This file
```

## Related resources

- [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md) — full deployment guide (configuration, architecture, security)
- [deployment/README-a2a.md](deployment/README-a2a.md) — A2A / Kagenti agent discovery deployment
- [deployment/docs/mlflow-tracing-setup.md](deployment/docs/mlflow-tracing-setup.md) — MLflow tracing setup
- [deployment/docs/mlflow-tracing.md](deployment/docs/mlflow-tracing.md) — tracing schema, backend comparisons, latency benchmarks
- [opendatahub-io/opencode](https://github.com/opendatahub-io/opencode) — container image source and CI
- [OpenCode upstream](https://github.com/sst/opencode) — upstream project
