# OpenClaw on OpenShift

> Tested: 2026-10-08 on OpenShift 4.22 with OpenClaw 2026.9.8 and vLLM model serving

**⚠ Important:** The container image used in this starter kit
(`ghcr.io/openclaw/openclaw`) is built and published by the
[OpenClaw upstream community](https://github.com/openclaw/openclaw),
**not by Red Hat**. It has not been built, scanned, or validated
according to Red Hat standards. Use it at your own discretion.
A Red Hat supported image may be provided in a future release.

Deploy [OpenClaw](https://github.com/openclaw/openclaw) on Red Hat OpenShift with vLLM model serving. The base manifests need no cluster-admin. The MLflow tracing path and the OpenShell sandbox path need cluster-scoped permissions (a created ClusterRole for tracing, and a ClusterRole, ClusterRoleBinding, and the Agent Sandbox CRDs for OpenShell).

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
              |  | init-config (seeds state)      |  |
              |  +--------------------------------+  |
              |  +--------------------------------+  |
              |  | gateway  port 18789            |  |
              |  | + Secret, ConfigMap mounts     |  |
              |  +--------------------------------+  |
              |  +--------------------------------+  |
              |  | otel-collector (optional,      |  |
              |  | mlflow-tracing overlay)        |  |
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
| `manifests/01-secret.yaml` | Gateway authentication token and `VLLM_API_KEY` |
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
| Model endpoint URL | `manifests/02-configmap.yaml` directly, or `overlays/<env>/configmap-patch.yaml` |
| Storage class | `manifests/03-pvc.yaml` directly, or `overlays/<env>/kustomization.yaml` (patch) |
| Namespace | `overlays/<env>/kustomization.yaml` (`namespace:` field) |
| Gateway token and `VLLM_API_KEY` | `manifests/01-secret.yaml` |
| Resource limits | Patch `manifests/04-deployment.yaml` |

## Docs

| Document | Description |
|----------|-------------|
| [docs/raw-deployment.md](docs/raw-deployment.md) | Full deployment guide: configuration, validation, troubleshooting |
| [docs/mlflow-tracing.md](docs/mlflow-tracing.md) | MLflow tracing with OTel collector sidecar (see also [shared TLS/RBAC guide](../../../docs/mlflow-openshift-auth-and-tls.md)) |
| [docs/model-compatibility.md](docs/model-compatibility.md) | Model testing results for agentic tool-calling |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes |
| [docs/installer-deployment.md](docs/installer-deployment.md) | Alternative deployment via [claw-installer](https://github.com/sallyom/claw-installer) |

## Related Projects

- [OpenClaw](https://github.com/openclaw/openclaw) — Upstream project
- [claw-installer](https://github.com/sallyom/claw-installer) — Web-based deployment tool with OpenShift plugin
- [openclaw-on-openshift](https://github.com/aakankshaduggal/openclaw-on-openshift) — Source repo with full docs

---

## Running in an OpenShell Sandbox

To run OpenClaw inside an [OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, use the `Containerfile.openshell`. This builds on the shared base image (`sandboxes/base/`) and adds Node.js and the OpenClaw CLI on top.

### Build and push the image

Since OpenShell 0.1, `openshell sandbox create --from` takes an image reference or a rootfs tar archive (`.tar`, `.tar.gz`, or `.tgz`). This recipe uses an image reference, and a gateway running on a cluster pulls that image from a registry. Build the image and push it to a registry your cluster can pull from:

```bash
podman build --platform linux/amd64 -t <registry>/<namespace>/openclaw-sandbox:latest -f Containerfile.openshell .
podman push <registry>/<namespace>/openclaw-sandbox:latest
```

### Create a sandbox

Start the OpenClaw gateway as the sandbox's main process:

```bash
openshell sandbox create --name openclaw --detach \
  --from <registry>/<namespace>/openclaw-sandbox:latest \
  -- openclaw gateway --bind loopback --auth none --port 18789 --allow-unconfigured
```

The `--allow-unconfigured` flag starts the gateway without a model provider. Configure it with `openshell sandbox exec openclaw -- openclaw config patch --stdin`; the config persists at `/sandbox/.openclaw/openclaw.json` on the sandbox volume. An API key for a self-hosted endpoint requires an imported provider profile, since a profile that only repoints a base URL is treated as endpointless.

Forward the gateway port to your machine, then open `http://localhost:18789`:

```bash
openshell forward start 18789 openclaw --background
```

### Allow access to the model endpoint

The sandbox policy denies all network egress by default. Allow the Node.js binary that runs OpenClaw to reach your model endpoint:

```bash
openshell policy update openclaw \
  --add-endpoint <model-host>:<port> \
  --binary /usr/local/bin/node \
  --rule-name model_endpoint --wait
```

The `--binary` value must be the resolved path of the executable (`/usr/local/bin/node` in this image). OpenShell matches the path the kernel reports for the process, not a symlink.

### What `Containerfile.openshell` does

Builds on the shared base image (`quay.io/hmoghani/openshell-base`) which provides the `sandbox` user, system packages, and the default sandbox policy. This flavor adds:

- Node.js from the official nodejs.org build (version pinned, checksum verified). OpenClaw 2026.9 needs Node.js 24.16 or newer with a WAL-reset-safe SQLite; the UBI Node.js packages link the system SQLite 3.46.1, which OpenClaw refuses to run on.
- OpenClaw via npm (version pinned, MIT)

### Notes

- On Kubernetes, OpenShell runs the supervisor in its own separate pod, and inside the workload `openshell-sandbox` overrides the image command (running as PID 1 applies only to the VM runtime). The command after `--` becomes the sandbox's main process. Without a command, the sandbox starts a shell, and you start the gateway by hand: `openclaw gateway --bind loopback --auth none --port 18789 --allow-unconfigured`
- On OpenShift, OpenShell runs the sandbox with a UID and GID from the namespace's range. The sandbox works in `/sandbox`; `/workspace` from the base image is not writable there.
- Remove sandboxes created with OpenShell 0.0.x before an upgrade to 0.1, then recreate them afterward.
- Build with `--platform linux/amd64` when targeting x86_64 clusters from Apple Silicon machines.
- Tested on OpenShell v0.1.2 (Helm chart 0.1.2), OpenShift 4.22 (October 2026).
