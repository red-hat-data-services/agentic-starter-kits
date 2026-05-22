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

### Option B: Kustomize

```bash
oc new-project my-openclaw

# Copy and customize the example overlay
cp -r overlays/example overlays/my-env
# Edit overlays/my-env/configmap-patch.yaml with your vLLM endpoint
# Edit overlays/my-env/kustomization.yaml with your namespace and storage class

oc apply -k overlays/my-env
```

### Option C: Direct YAML apply

```bash
oc new-project my-openclaw

# Edit manifests/02-configmap.yaml with your model endpoint
# Edit manifests/01-secret.yaml with your gateway token

oc apply -k manifests/
```

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
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes (route 503, model override, heartbeat, config clobber) |
| [docs/model-compatibility.md](docs/model-compatibility.md) | Model testing results for agentic tool-calling |

## Related Projects

- [claw-installer](https://github.com/sallyom/claw-installer) — Web-based deployment tool with OpenShift plugin
- [openclaw-on-openshift](https://github.com/aakankshaduggal/openclaw-on-openshift) — Source repo with full docs
- [OpenClaw](https://github.com/openclaw/openclaw) — Upstream project
