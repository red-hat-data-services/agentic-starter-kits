# OpenClaw on OpenShift

> Tested: 2026-04-13 on OpenShift 4.19 (ROSA) with vLLM model serving

**⚠ Important:** The container image used in this starter kit
(`ghcr.io/openclaw/openclaw`) is built and published by the
[OpenClaw upstream community](https://github.com/openclaw/openclaw),
**not by Red Hat**. It has not been built, scanned, or validated
according to Red Hat standards. Use it at your own discretion.
A Red Hat supported image may be provided in a future release.

Deploy [OpenClaw](https://github.com/openclaw/openclaw) on Red Hat OpenShift with vLLM model serving — no cluster-admin required.

For the full deployment guide, see [docs/raw-deployment.md](docs/raw-deployment.md).

## Prerequisites

- OpenShift 4.17+ with namespace-scoped access (`oc login`)
- A model serving endpoint (vLLM, KServe, or external API)
- Block storage class (gp3-csi, managed-csi, thin-csi) — not NFS

## Quick Start

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
              |            Service                   |
              |        (ClusterIP :18789)            |
              +------------------+------------------+
                                 |
                                 v
              +------------------+------------------+
              |              Pod                     |
              |  +--------------------------------+  |
              |  | gateway                        |  |
              |  | port 18789                     |  |
              |  +---------------+----------------+  |
              |                  |                   |
              |           +------+------+            |
              |           | PVC (5Gi)   |            |
              |           +-------------+            |
              +--------------------------------------+
                         |
                         | OpenAI-compatible API
                         v
              +---------------------------+
              |  vLLM / KServe / API      |
              +---------------------------+
```

## Files

| File | Description |
|------|-------------|
| `manifests/01-secret.yaml` | Gateway authentication token |
| `manifests/02-configmap.yaml` | Model endpoint and gateway configuration |
| `manifests/03-pvc.yaml` | Persistent storage for gateway state |
| `manifests/04-deployment.yaml` | OpenClaw gateway deployment |
| `manifests/05-service.yaml` | ClusterIP service |
| `manifests/06-route.yaml` | TLS edge route |
| `manifests/kustomization.yaml` | Kustomize entrypoint |
| `overlays/example/` | Example overlay for environment-specific config |
| `overlays/mlflow-tracing/` | MLflow tracing via OTel collector sidecar |
| `Containerfile.openshell` | OpenShell sandbox image build |

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
| [docs/raw-deployment.md](docs/raw-deployment.md) | Full deployment guide: configuration, validation, troubleshooting |
| [docs/mlflow-tracing.md](docs/mlflow-tracing.md) | MLflow tracing with OTel collector sidecar |
| [docs/model-compatibility.md](docs/model-compatibility.md) | Model testing results for agentic tool-calling |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes |
| [docs/installer-deployment.md](docs/installer-deployment.md) | Alternative deployment via [claw-installer](https://github.com/sallyom/claw-installer) |

## Related Projects

- [OpenClaw](https://github.com/openclaw/openclaw) — Upstream project
- [claw-installer](https://github.com/sallyom/claw-installer) — Web-based deployment tool with OpenShift plugin
- [openclaw-on-openshift](https://github.com/aakankshaduggal/openclaw-on-openshift) — Source repo with full docs

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
