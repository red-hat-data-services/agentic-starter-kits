# Deploying OpenClaw on OpenShift with Raw Manifests

> Tested: 2026-06-10 on OpenShift 4.19 (ROSA) with OpenClaw 2026.6.5, vLLM via OGX 1.0.2

Deploy [OpenClaw](https://github.com/openclaw/openclaw) on OpenShift using raw Kustomize manifests. This approach gives full control over the deployment configuration without the openclaw-installer abstraction. See [installer-deployment.md](installer-deployment.md).

## Prerequisites

- **OpenShift 4.17+** with namespace-scoped access (`oc login`)
- **Block storage class** (gp3-csi, managed-csi, thin-csi) — not NFS (SQLite requires POSIX file locking)
- **A vLLM-compatible model endpoint** — either:
  - Direct vLLM server with `--enable-auto-tool-choice --tool-call-parser openai`
  - OGX gateway proxying to vLLM (see [model-compatibility.md](model-compatibility.md) for tested models)

### Verify prerequisites

```bash
oc version
oc whoami
oc get storageclass
```

### Find your model ID

Query your model endpoint to discover the exact model ID. The ID format differs depending on whether you use vLLM directly or through OGX:

```bash
curl -s https://<your-endpoint>/v1/models | python3 -m json.tool
```

**Direct vLLM** returns the raw model name:

```text
{
  "data": [
    {
      "id": "gpt-oss-120b",
      "owned_by": "vllm"
    }
  ]
}
```

**OGX gateway** prefixes the model with `vllm/`:

```text
{
  "data": [
    {
      "id": "vllm/gpt-oss-120b",
      "owned_by": "ogx"
    }
  ]
}
```

Use the **exact** `id` value from the response as `models[].id` in your ConfigMap. For `agents.defaults.model`, prepend `vllm/` (the provider name) to the model ID.

## Configuration

### Step 1: Set the model endpoint

Edit `manifests/02-configmap.yaml` and replace the placeholder values:

- `YOUR-VLLM-OR-OGX-ENDPOINT` — your vLLM or OGX endpoint hostname
- `YOUR-MODEL-ID` — the model ID from the `/v1/models` query above

**Via OGX gateway** — OGX prefixes model IDs with `vllm/`, so `agents.defaults.model` ends up as `vllm/vllm/<model>` (provider prefix + OGX model ID — the double `vllm/` is intentional):

```json
"agents": {
  "defaults": {
    "model": "vllm/vllm/gpt-oss-120b"
  }
},
"models": {
  "providers": {
    "vllm": {
      "baseUrl": "https://ogx-my-namespace.apps.my-cluster.example.com/v1",
      "apiKey": "not-needed",
      "models": [{
        "id": "vllm/gpt-oss-120b",
        "name": "vllm/gpt-oss-120b"
      }]
    }
  }
}
```

**Direct vLLM**

```json
"agents": {
  "defaults": {
    "model": "vllm/gpt-oss-120b"
  }
},
"models": {
  "providers": {
    "vllm": {
      "baseUrl": "https://vllm-my-model.apps.my-cluster.example.com/v1",
      "apiKey": "not-needed",
      "models": [{
        "id": "gpt-oss-120b",
        "name": "gpt-oss-120b"
      }]
    }
  }
}
```

Notice the `agents.defaults.model` field uses the format `<provider>/<model-id>`, while the `models[].id` is the raw ID sent to the endpoint in API requests.

### Step 2: Set secrets

Edit `manifests/01-secret.yaml`:

- `OPENCLAW_GATEWAY_TOKEN` — replace `CHANGE-ME` with a token for the Control UI
- `VLLM_API_KEY` — set to your vLLM/OGX API key, or leave as `not-needed` for unauthenticated endpoints

### Step 3: Check the storage class

Edit `manifests/03-pvc.yaml` if your cluster uses a different block storage class than `gp3-csi`.

**Alternative: use an overlay** to keep the base manifests untouched:

```bash
cp -r overlays/example overlays/my-env
# Edit overlays/my-env/configmap-patch.yaml with your endpoint + model
# Edit overlays/my-env/kustomization.yaml with your namespace + storage class
oc apply -k overlays/my-env
```

## Deployment

```bash
oc new-project my-openclaw

oc apply -k manifests/ -n my-openclaw
```

### Verify startup

```bash
oc get pods -n my-openclaw
```

Expected: `1/1 Running` (init container completes, gateway starts).

```bash
oc logs deployment/openclaw -c gateway -n my-openclaw --tail=20
```

Expected output:

```text
[gateway] loading configuration…
[gateway] resolving authentication…
[gateway] starting...
[gateway] agent model: vllm/<your-model> (thinking=off, fast=off)
[gateway] http server listening (... plugins; ...s)
[gateway] ready
```

### Access the Control UI

Port-forward to access locally:

```bash
oc port-forward deployment/openclaw 18789:18789 -n my-openclaw
```

Open <http://localhost:18789> in your browser. Paste the gateway token from Step 2 when prompted.

On first connect, device pairing is auto-approved for local connections. You should see the chat interface ready to use.

## Next: Enable tracing (optional)

To send OpenTelemetry traces to RHOAI MLflow, see [mlflow-tracing.md](mlflow-tracing.md).

## References

| Resource | URL |
|----------|-----|
| OpenClaw vLLM Provider Docs | <https://docs.openclaw.ai/providers/vllm> |
| OpenClaw K8s Deployment Scripts | <https://github.com/openclaw/openclaw/tree/main/scripts/k8s> |
| OpenClaw Upstream | <https://github.com/openclaw/openclaw> |
