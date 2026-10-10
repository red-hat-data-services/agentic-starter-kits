# Deploying OpenClaw on OpenShift with Raw Manifests

> Tested: 2026-10-08 on OpenShift 4.22 with OpenClaw 2026.9.8 (fresh install, and upgrade of a 2026.6.5 deployment), vLLM (Red Hat AI Inference Server 3.3, CPU) serving Qwen2.5-0.5B-Instruct
>
> Previously tested: 2026-06-10 on OpenShift 4.19 (ROSA) with OpenClaw 2026.6.5, vLLM via OGX 1.0.2

Deploy [OpenClaw](https://github.com/openclaw/openclaw) on OpenShift using raw Kustomize manifests. This approach gives full control over the deployment configuration without the openclaw-installer abstraction. See [installer-deployment.md](installer-deployment.md).

## Prerequisites

- **OpenShift 4.17+** with namespace-scoped access (`oc login`)
- **Block storage class** (gp3-csi, managed-csi, thin-csi) — not NFS (SQLite requires POSIX file locking)
- **A vLLM-compatible model endpoint** — either:
  - Direct vLLM server with `--enable-auto-tool-choice` and a `--tool-call-parser` that matches the model family (`openai` for gpt-oss, `hermes` for Qwen)
  - OGX gateway proxying to vLLM (see [model-compatibility.md](model-compatibility.md) for tested models)

### Verify prerequisites

```bash
oc version
oc whoami
oc get storageclass
```

Check that the `Server Version` line reports 4.17 or newer. A namespace-scoped user often cannot read the server version and sees only the client version. If so, confirm the 4.17+ prerequisite another way, for example with your cluster administrator.

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

This is abbreviated. The real log also includes lines such as `log file:`, `native runtime:`, and `worker startup state:`, and it prints `[gateway] spawn broker ready` as well. A literal search for `[gateway] ready` can also miss the line, because `oc logs` output puts ANSI color codes between `[gateway]` and `ready`. Prefer a regex match (see the `grep -E "migrated|ready"` check under Upgrading) over a literal `[gateway] ready` search.

### Access the Control UI

The gateway accepts browser connections only from origins it knows. Without further configuration these are `http://localhost:18789` and `http://127.0.0.1:18789`, so a port-forward works right away; the Route needs one configuration change.

#### Through a port-forward

```bash
oc port-forward deployment/openclaw 18789:18789 -n my-openclaw
```

Open <http://localhost:18789> in your browser. Paste the gateway token from Step 2 when prompted.

On first connect, device pairing is auto-approved for local connections. You should see the chat interface ready to use.

#### Through the Route

Add the Route's address to the allowed origins:

```bash
ROUTE_HOST=$(oc get route openclaw -n my-openclaw -o jsonpath='{.spec.host}')
echo "{\"gateway\": {\"controlUi\": {\"allowedOrigins\": [\"https://${ROUTE_HOST}\"]}}}" | \
  oc exec -i deployment/openclaw -c gateway -n my-openclaw -- \
  node /app/dist/index.js config patch --stdin
```

Because arrays replace rather than merge in a config patch (see Update the configuration), this sets `allowedOrigins` to the Route alone and drops any origins added earlier. To keep existing entries, include them in the array alongside the Route.

The change applies without a restart. Open `https://<ROUTE_HOST>` in your browser and paste the gateway token. A browser behind the Route is not a local connection, so the gateway asks you to approve the device. List the pending request and approve it by its request ID (`devices approve --latest` only shows the newest request):

```bash
oc exec deployment/openclaw -c gateway -n my-openclaw -- node /app/dist/index.js devices list
oc exec deployment/openclaw -c gateway -n my-openclaw -- node /app/dist/index.js devices approve <request-id>
```

The Route sets `haproxy.router.openshift.io/set-forwarded-headers: never`, because on gateway-authenticated routes OpenClaw answers requests with forwarded headers from a proxy outside `gateway.trustedProxies` with HTTP 403 (`proxy_attribution_required`). The live probe path answers before proxy attribution, and plugin-authenticated routes may still answer. Do not add the cluster network to `gateway.trustedProxies` instead: on OVN-Kubernetes the kubelet's health probes come from the same node addresses as the router, and the gateway then rejects the probes as well.

> The Route makes the gateway reachable for everyone who can reach the cluster's router. Access still needs the gateway token and an approved device.

## Update the configuration

The init container copies `openclaw.json` from the ConfigMap only on the first start. After that, OpenClaw owns the copy on the PVC and keeps its runtime changes there. To change the configuration of a running deployment, send a patch to the OpenClaw CLI in the gateway container. Objects merge, arrays and scalars replace, and `null` deletes a key:

```bash
echo '{"models": {"providers": {"vllm": {"baseUrl": "https://NEW-ENDPOINT/v1"}}}}' | \
  oc exec -i deployment/openclaw -c gateway -n my-openclaw -- \
  node /app/dist/index.js config patch --stdin
```

OpenClaw refuses a patch that would drop model IDs from a provider's model list unless you pass `--replace-path` for that path. OpenClaw validates the patch before it writes it and reports whether the gateway needs a restart. Update the ConfigMap as well, so that a new PVC starts with the same configuration.

## Upgrading an existing deployment

Back up the OpenClaw state first, while no agent run is active:

```bash
oc exec deployment/openclaw -c gateway -n my-openclaw -- \
  tar czf - -C /home/node .openclaw > openclaw-backup.tgz
```

With manifests older than the OpenClaw 2026.9 update, the state lives at the root of the PVC: use `-C /home/node/.openclaw .` instead.

Then apply the updated manifests:

```bash
oc apply -k manifests/ -n my-openclaw
```

On the first start after the upgrade:

- The init container moves state that earlier versions of these manifests kept at the root of the PVC into `~/.openclaw`, so that OpenClaw owns its state directory.
- The image entrypoint runs `openclaw doctor --fix`, which migrates the state to the new OpenClaw version and saves a backup of the state database first. The startup probe allows 5 minutes for this.

Check the gateway log for `Auto-migrated legacy state` and `[gateway] ready`:

```bash
oc logs deployment/openclaw -c gateway -n my-openclaw | grep -E "migrated|ready"
```

## Uninstall

Remove the deployment with the same kustomization you applied. For the base manifests:

```bash
oc delete -k manifests/ -n my-openclaw
```

If you deployed through an overlay, delete that overlay instead:

```bash
oc delete -k overlays/my-env
```

This leaves the PVC and its OpenClaw state in place. Delete the project with `oc delete project my-openclaw` to remove everything, including the stored state.

## Next: Enable tracing (optional)

To send OpenTelemetry traces to RHOAI MLflow, see [mlflow-tracing.md](mlflow-tracing.md).

## References

| Resource | URL |
|----------|-----|
| OpenClaw vLLM Provider Docs | <https://docs.openclaw.ai/providers/vllm> |
| OpenClaw K8s Deployment Scripts | <https://github.com/openclaw/openclaw/tree/main/scripts/k8s> |
| OpenClaw Upstream | <https://github.com/openclaw/openclaw> |
