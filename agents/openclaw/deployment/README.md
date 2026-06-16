# OpenClaw on OpenShift

> Tested: 2026-04-13 on OpenShift 4.19 (ROSA) with vLLM model serving

Deploy [OpenClaw](https://github.com/openclaw/openclaw) on Red Hat OpenShift with vLLM model serving, OAuth SSO, and production-grade security — no cluster-admin required.

## Prerequisites

- OpenShift 4.17+ with namespace-scoped access (`oc login`)
- A model serving endpoint (vLLM, KServe, or external API)
- Block storage class (gp3-csi, managed-csi, thin-csi) — not NFS

## Quick Start

### Option A: Using claw-installer (recommended)

The [claw-installer](https://github.com/sallyom/claw-installer) handles OAuth proxy, Routes, ServiceAccounts, and lifecycle management automatically.

```bash
git clone https://github.com/sallyom/claw-installer.git
cd claw-installer
npm install && npm run build && npm run dev
# Open http://localhost:3000, select OpenShift, fill in the form
```

See [docs/installer-deployment.md](docs/installer-deployment.md) for the full walkthrough, validation, and rollback procedures.

### Option B: Raw Manifests (Kustomize or direct apply)

```bash
oc new-project my-openclaw

# Edit manifests/02-configmap.yaml with your model endpoint
# Edit manifests/01-secret.yaml with your gateway token

oc apply -k manifests/
```

See [docs/raw-deployment.md](docs/raw-deployment.md) for the full walkthrough, configuration details, and troubleshooting.

## Architecture

```text
                     +-----------------------+
                     |   OpenShift Route     |
                     |   (TLS edge)          |
                     +-----------+-----------+
                                 |
                                 v
              +------------------+------------------+
              |              Pod                     |
              |  +---------------+  +-------------+  |
              |  | oauth-proxy   |  | gateway     |  |
              |  | port 8443     +->| port 18789  |  |
              |  | (OpenShift    |  | (loopback)  |  |
              |  |  OAuth SSO)   |  |             |  |
              |  +---------------+  +------+------+  |
              |                            |          |
              |                     +------+------+   |
              |                     | PVC (5Gi)   |   |
              |                     +-------------+   |
              +--------------------------------------+
                         |
                         | OpenAI-compatible API
                         v
              +---------------------------+
              |  vLLM / KServe / API      |
              +---------------------------+
```

## Customization

| What | Where |
|------|-------|
| Model endpoint URL | `overlays/<env>/configmap-patch.yaml` |
| Storage class | `overlays/<env>/kustomization.yaml` (patch) |
| Namespace | `overlays/<env>/kustomization.yaml` (`namespace:` field) |
| Gateway token | `manifests/01-secret.yaml` |
| Resource limits | Patch `manifests/04-deployment.yaml` |

## Docs

| Document | Description |
|----------|-------------|
| [docs/installer-deployment.md](docs/installer-deployment.md) | Full deployment guide: prerequisites, validation, rollback, appendix |
| [docs/raw-deployment.md](docs/raw-deployment.md) | Step-by-step guide for deploying with raw Kustomize manifests |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes (route 503, model override, heartbeat, config clobber) |
| [docs/model-compatibility.md](docs/model-compatibility.md) | Model testing results for agentic tool-calling |

## Related Projects

- [claw-installer](https://github.com/sallyom/claw-installer) — Web-based deployment tool with OpenShift plugin
- [openclaw-on-openshift](https://github.com/aakankshaduggal/openclaw-on-openshift) — Source repo with full docs
- [OpenClaw](https://github.com/openclaw/openclaw) — Upstream project

---

## Running in an OpenShell Sandbox

To run OpenClaw inside an [OpenShell](https://github.com/NVIDIA/OpenShell-Community) sandbox, use the `Containerfile.openshell`. This builds on the shared base image (`sandboxes/base/`) and adds Node.js and the OpenClaw CLI on top.

### Build the OpenShell-compatible image

```bash
podman build --platform linux/amd64 -t openclaw-sandbox:latest -f Containerfile.openshell .
```

### Create a sandbox

```bash
openshell sandbox create --from openclaw-sandbox:latest
```

### What `Containerfile.openshell` does

Builds on the shared base image (`quay.io/hmoghani/openshell-base`) which provides the `sandbox` user, system packages, and OpenShell entrypoint. This flavor adds:

- Node.js and npm (from UBI repos)
- OpenClaw via npm (version pinned, MIT)

### Notes

- OpenShell's supervisor takes over as PID 1 and does not automatically start the OpenClaw gateway. Start it manually inside the sandbox: `openclaw gateway --bind loopback --auth none --port 18789 --allow-unconfigured`
- Build with `--platform linux/amd64` when targeting x86_64 clusters from Apple Silicon machines.
- Tested on OpenShell v0.0.58, OpenShift 4.21 (June 2026).
