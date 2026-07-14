# OpenCode on Red Hat OpenShift AI — Deployment Guide

This guide covers deploying [OpenCode](https://opencode.ai) as a coding agent on Red Hat OpenShift AI, including image versioning, configuration, and two deployment modes (web and CLI).

## Container Image

| Field | Value |
|-------|-------|
| Image | `quay.io/opendatahub/odh-opencode-rhel9:20260619-194847e` |
| OpenCode version | Built from [opendatahub-io/opencode](https://github.com/opendatahub-io/opencode) |
| Base | UBI 9 minimal |
| License | MIT (OpenCode), Apache 2.0 (deployment manifests) |

### What the image contains

| Layer | Purpose |
|-------|---------|
| UBI 9 minimal | RHEL-compatible base |
| OpenCode | Go binary built from source |
| git, jq, make, vim-minimal, diffutils, findutils, openssh-clients, patch, procps-ng, tar, gzip, which | CLI tools for development workflows |
| Python 3 + [uv](https://github.com/astral-sh/uv) | Python environment and package manager |

### Version pinning strategy

- **OpenCode**: pinned to a tagged release in the Containerfile `ARG`. Upgrades require a new image build and manifest update.
- **Go runtime**: build-time only; not present in the final image (multi-stage build).
- **Base image**: `registry.access.redhat.com/ubi9/ubi-minimal`, pulled at build time. Pin to a specific tag for reproducible builds.
- **Image tag in manifests**: pin to a specific tag or digest in production. Avoid `:latest`.

## Prerequisites

- OpenShift 4.17+ cluster with `oc` CLI authenticated
- A model serving endpoint — vLLM, KServe, RHOAI model serving, or OGX — exposing an OpenAI-compatible API on a cluster-internal Service
- Block storage class (gp3-csi, managed-csi, thin-csi) for the workspace PVC

## Project Structure

```text
deployment/
├── manifests/                    # Base kustomize manifests (web mode + OAuth)
│   ├── kustomization.yaml        # Kustomize entrypoint
│   ├── namespace.yaml
│   ├── serviceaccount.yaml
│   ├── deployment.yaml           # Two-container pod (oauth-proxy + opencode)
│   ├── service.yaml
│   ├── route.yaml
│   ├── pvc.yaml
│   ├── entrypoint.sh             # Container entrypoint (config, MCP, mode switching)
│   └── config-template.json      # OpenCode provider config (vLLM + OGX)
├── overlays/
│   ├── cli/                      # CLI mode (no OAuth, no Route, oc exec)
│   ├── example/                  # Template for custom environments
│   └── mlflow-tracing/           # MLflow tracing integration
├── Containerfile.openshell       # OpenShell sandbox variant
├── Containerfile.mlflow          # MLflow tracing image variant
├── README.md                     # OpenShell sandbox guide
├── DEPLOYMENT.md                 # This file
└── docs/                         # MLflow tracing documentation
```

## Deployment

### Quick start (web mode with OAuth)

```bash
# From the repo root
cd agents/opencode/deployment

# Edit manifests/kustomization.yaml with your vLLM endpoint, API key, and model name
oc apply -k manifests/

oc -n opencode rollout status deployment/opencode-web
oc -n opencode get route opencode-web -o jsonpath='https://{.spec.host}{"\n"}'
```

Open the route URL in your browser. OpenShift OAuth handles authentication.

### CLI mode (headless, `oc exec`)

```bash
oc apply -k overlays/cli

oc -n opencode rollout status deployment/opencode-web
oc -n opencode exec -it deployment/opencode-web -c opencode-web -- opencode
```

No OAuth proxy or Route is created. Useful for interactive terminal sessions or CI pipelines.

### Custom environment

```bash
cp -r overlays/example overlays/my-env
# Edit overlays/my-env/kustomization.yaml — namespace, model, storage class
oc apply -k overlays/my-env
```

### MLflow tracing

```bash
oc apply -k overlays/mlflow-tracing
```

See [docs/mlflow-tracing-setup.md](docs/mlflow-tracing-setup.md) for full configuration details.

## Configuration

| Setting | Where to change | Notes |
|---------|----------------|-------|
| Model endpoint URL | `manifests/kustomization.yaml` (`BASE_URL`) | Cluster-internal DNS, e.g. `http://vllm-svc.vllm.svc.cluster.local/v1` |
| API key | `manifests/kustomization.yaml` (`API_KEY`) | Use `"token"` if auth is disabled |
| Model name | `manifests/kustomization.yaml` (`MODEL_NAME`) | Must match the model loaded in vLLM |
| Small model | `manifests/config-template.json` (`small_model`) | Defaults to `MODEL_NAME`; edit the template to use a separate placeholder (e.g. `${SMALL_MODEL_NAME}`) for lighter tasks |
| Storage class | `manifests/kustomization.yaml` (patch section) | Default PVC is 10Gi |
| MCP servers | ConfigMap `opencode-web-mcp` | Optional; merged into config at startup |
| Provider (vLLM vs OGX) | `manifests/config-template.json` (`enabled_providers`) | Both enabled by default |

### Session Persistence

OpenCode session history and workspace files persist across pod restarts. The container's working directory is set to the PVC mount (`/opt/app-root/workspace`), so files created during a session are stored on persistent storage. The entrypoint additionally redirects OpenCode's internal data directories to PVC-backed paths.

#### How It Works

| Default Path               | Redirected To                                       | Purpose                   |
|----------------------------|-----------------------------------------------------|---------------------------|
| `~/.config/opencode/`      | `/opt/app-root/workspace/.opencode/config/opencode/`| Configuration, settings   |
| `~/.local/share/opencode/` | `/opt/app-root/workspace/.opencode/data/opencode/`  | Session history, database |
| `~/.local/state/opencode/` | `/opt/app-root/workspace/.opencode/state/opencode/` | Locks, runtime state      |

The entrypoint creates symlinks from default XDG locations to PVC-backed paths and exports `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME` to point at the persistent directories.

> **Note**: The container image creates `~/.local/state/` with 755 permissions, which prevents symlink creation under OpenShift's random UID (the root group cannot write to 755 directories). The entrypoint's `XDG_STATE_HOME` export works around this. If this is fixed upstream in the container image (by using 775 permissions), the workaround can be removed.

#### Resuming Sessions (CLI Mode)

```bash
# List previous sessions
oc exec deployment/opencode-cli -- opencode session list

# Resume the most recent session
oc exec -it deployment/opencode-cli -- opencode --continue

# Resume a specific session
oc exec -it deployment/opencode-cli -- opencode --session <session-id>
```

#### Customizing the Data Directory

Override the default location by setting the `OPENCODE_DATA_DIR` environment variable in the deployment:

```yaml
env:
  - name: OPENCODE_DATA_DIR
    value: /opt/app-root/workspace/my-custom-dir
```

The entrypoint creates `config/opencode/`, `data/opencode/`, and `state/opencode/` subdirectories within this path.

### Skills Injection

Skills extend OpenCode with custom instructions. No skills are included by default — you create and inject your own.

Skills are auto-discovered from `~/.config/opencode/skills/`. The skills ConfigMap is mounted at `/etc/opencode-skills/` and the entrypoint symlinks it into the config directory. Each skill must be in a subdirectory containing a `SKILL.md` file with YAML frontmatter.

#### Example: Creating a Code Review Skill

**1. Create a `SKILL.md` file:**

```markdown
---
name: code-review
description: Analyze code for correctness, security, and performance issues
---

# Code Review

When reviewing code, analyze for:

1. **Correctness** - Logic errors, edge cases, off-by-one errors
2. **Security** - Input validation, injection risks, hardcoded secrets
3. **Performance** - Unnecessary loops, N+1 queries, missing indexes
```

**2. Create a ConfigMap from your skill files:**

```bash
oc create configmap opencode-web-skills \
  --from-file=code-review-skill=./skills/code-review/SKILL.md
```

**3. Add an `items` mapping to the skills volume in your deployment manifest:**

The `items` mapping creates the subdirectory structure OpenCode expects:

```yaml
volumes:
  - name: skills
    configMap:
      name: opencode-web-skills
      optional: true
      items:
        - key: code-review-skill
          path: code-review/SKILL.md
```

**4. Restart the deployment:**

```bash
oc rollout restart deployment/opencode-web
```

## Security

- **SCC**: Runs under `restricted-v2` — `runAsNonRoot`, drop all capabilities, seccomp RuntimeDefault. No special SCC grants required.
- **TLS**: Reencrypt termination end-to-end; serving certificate auto-generated by OpenShift.
- **RBAC**: OAuth proxy enforces Subject Access Review — users must have `get` on `services` in the deployment namespace.
- **Secrets**: Inline secrets in `kustomization.yaml` are for convenience only. For production, use Sealed Secrets, External Secrets Operator, or Secrets Store CSI Driver.

## Architecture

The web mode deployment runs a two-container pod:

1. **oauth-proxy** — OpenShift OAuth proxy sidecar handling authentication via TLS on port 8443
2. **opencode-web** — OpenCode application serving the web UI on port 8003

The entrypoint script (`manifests/entrypoint.sh`) handles:

- Persistence — working directory is `/opt/app-root/workspace` (PVC mount), so workspace files survive pod restarts
- Session data redirection — symlinks OpenCode's config, data, and state directories from default XDG locations to PVC-backed paths under `.opencode/`
- Git workspace initialization
- Config template variable substitution (BASE_URL, API_KEY, MODEL_NAME)
- Skills injection — symlinks ConfigMap-mounted skills into the config directory
- Optional MCP server config injection from a ConfigMap
- Mode switching between web and CLI

## Comparison: OpenShell sandbox vs kustomize deployment

| | OpenShell sandbox | Kustomize deployment |
|--|-------------------|---------------------|
| **Image** | `openshell-base` + npm flavor | `odh-opencode-rhel9` (Go binary) |
| **Runtime** | Inside OpenShell gateway | Standalone pod on OpenShift |
| **Auth** | OpenShell gateway | OpenShift OAuth proxy |
| **Use case** | Sandboxed experimentation | Production RHOAI deployment |
| **Manifests** | N/A (OpenShell manages lifecycle) | `manifests/` in this directory |

## Related resources

- [opendatahub-io/opencode](https://github.com/opendatahub-io/opencode) — container image source and CI
