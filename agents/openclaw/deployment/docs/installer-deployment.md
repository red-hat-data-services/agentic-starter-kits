# Deploying OpenClaw on OpenShift with openclaw-installer

> Tested: 2026-04-13 on OpenShift 4.19 (ROSA) with vLLM model serving

Step-by-step guide for deploying OpenClaw on an OpenShift cluster using the [openclaw-installer](https://github.com/sallyom/claw-installer). This is the recommended deployment method — it handles OAuth proxy, ServiceAccounts, Routes, and lifecycle management automatically.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Deployment Steps](#deployment-steps)
- [Validation](#validation)
- [Instance Management](#instance-management)
- [Rollback Instructions](#rollback-instructions)
- [Appendix](#appendix)

## Prerequisites

### Environment Requirements

- **OpenShift Version:** 4.17+ (tested on 4.19.18)
- **Access Level:** Namespace-scoped — no cluster-admin needed
- **CLI Tools:** `oc` (OpenShift CLI), `node` (Node.js 22+), `git`
- **Storage:** Block storage class (gp3-csi, managed-csi, thin-csi) — avoid NFS (SQLite requires POSIX file locking)
- **Model Endpoint:** vLLM, KServe, or external API (OpenAI, Anthropic, Vertex AI)

### Verify Prerequisites

```bash
# Verify oc CLI
oc version
```

Expected output:

```text
Client Version: 4.17.0
...
```

```bash
# Verify cluster access
oc whoami
```

Expected output:

```text
<your-username>
```

```bash
# Verify Node.js
node --version
```

Expected output:

```text
v22.x.x
```

```bash
# Check available storage classes
oc get storageclass
```

Expected output (look for a block storage class):

```text
NAME            PROVISIONER       RECLAIMPOLICY   ...
gp3-csi         ebs.csi.aws.com   Delete          ...
```

## Architecture Overview

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
              |                     | PVC (10Gi)  |   |
              |                     +-------------+   |
              +--------------------------------------+
                         |
                         | OpenAI-compatible API
                         v
              +---------------------------+
              |  vLLM / KServe / API      |
              +---------------------------+
```

## Deployment Steps

### Step 1: Create your namespace

```bash
oc login --token=<your-token> --server=https://api.<your-cluster>:443
oc new-project <your-name>-openclaw
```

Expected output:

```text
Now using project "<your-name>-openclaw" on server "https://api.<your-cluster>:443".
```

### Step 2: Start the installer

```bash
git clone https://github.com/sallyom/claw-installer.git
cd openclaw-installer
npm install && npm run build && npm run dev
```

Expected output:

```text
> openclaw-installer@x.x.x dev
> next dev

  ▲ Next.js x.x.x
  - Local:    http://localhost:3000
```

Open `http://localhost:3000`. The installer auto-detects your OpenShift cluster and loads the OpenShift provider plugin.

### Step 3: Fill in the deploy form

| Field | Value | Notes |
|-------|-------|-------|
| **Agent name** | your choice | e.g., `my-agent` |
| **Project / Namespace** | your namespace | e.g., `my-openclaw` |
| **Image** | `ghcr.io/openclaw/openclaw:latest` | |
| **Provider** | Self-hosted (vLLM) | or Anthropic/OpenAI/Vertex AI if using cloud |
| **Model endpoint** | your vLLM URL | e.g., `https://vllm-20b-gpt-oss.apps.rosa.<cluster>/v1` |

Click **Deploy**. The installer streams logs as it creates each resource.

Expected output (installer log panel):

```text
Creating ServiceAccount...        ✓
Creating Secrets...                ✓
Creating ConfigMap...              ✓
Creating PVC...                    ✓
Creating Deployment...             ✓
Creating Service...                ✓
Creating Route...                  ✓
Deployment complete.
```

### Step 4: Verify pod startup

```bash
oc get pods -n <namespace>
```

Expected output:

```text
NAME                       READY   STATUS    RESTARTS   AGE
openclaw-xxxxxxxxxx-xxxxx  2/2     Running   0          60s
```

> **Note:** `2/2` indicates both the oauth-proxy and gateway containers are running. If you see `1/2` or `CrashLoopBackOff`, check [troubleshooting.md](troubleshooting.md).

### Step 5: Fix the Route (if needed)

Open the Route URL:

```bash
oc get route openclaw -n <namespace> -o jsonpath='{.spec.host}'
```

Navigate to `https://<route-host>` in your browser. If you see "Application is not available", the TLS termination is misconfigured. See [troubleshooting.md](troubleshooting.md#route-returns-application-is-not-available-503).

**Verification:**

```bash
curl -s -o /dev/null -w "%{http_code}" -k https://$(oc get route openclaw -n <namespace> -o jsonpath='{.spec.host}')
```

Expected output:

```text
403
```

> A `403` is correct — it means the OAuth proxy is running and will redirect you to OpenShift SSO. A `503` means the Route is misconfigured.

### Step 6: Approve device pairing

After SSO login, the Control UI requires a one-time device pairing. Get the request ID from the UI prompt, then:

```bash
oc exec deployment/openclaw -n <namespace> -c gateway -- \
  openclaw devices approve <request-id>
```

Expected output:

```text
Device approved: <request-id>
```

Or use the **Open** action from the installer's **Instances** tab — it opens with the token pre-filled and may auto-pair.

### Step 7: Verify model configuration

Check the gateway logs to confirm the correct model is loaded:

```bash
oc logs deployment/openclaw -c gateway -n <namespace> | grep "agent model"
```

Expected output:

```text
[gateway] agent model: openai-compat/gpt-oss-20b
```

If it shows a different model (e.g., `anthropic/claude-sonnet-4-6`), the gateway auto-detected a provider and overrode your config. See [troubleshooting.md](troubleshooting.md#gateway-uses-wrong-model--no-api-key-errors).

## Validation

After completing the deployment steps, validate each component:

### 1. Pod Health

```bash
oc get pods -n <namespace>
```

Expected: All pods show `2/2 Running` status with zero restarts.

### 2. Route Accessibility

```bash
curl -s -o /dev/null -w "%{http_code}" -k \
  https://$(oc get route openclaw -n <namespace> -o jsonpath='{.spec.host}')
```

Expected: `403` (OAuth redirect gate).

### 3. Gateway Logs

```bash
oc logs deployment/openclaw -c gateway -n <namespace> | grep -E "(ready|agent model|heartbeat)"
```

Expected output:

```text
[gateway] agent model: openai-compat/gpt-oss-20b
[gateway] ready (4 plugins: ...; 3.xs)
[heartbeat] disabled
```

### 4. OAuth Proxy Logs

```bash
oc logs deployment/openclaw -c oauth-proxy -n <namespace> --tail=5
```

Expected: No error lines. Should show listening messages.

### 5. PVC Bound

```bash
oc get pvc -n <namespace>
```

Expected:

```text
NAME               STATUS   VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
openclaw-home-pvc  Bound    ...      10Gi       RWO            gp3-csi        5m
```

### 6. End-to-End Test

After device pairing, send a test message in the Control UI. The agent should respond using the configured model. If you see "No API key found" errors, the model provider isn't configured correctly — see [troubleshooting.md](troubleshooting.md).

## What the installer creates

| Resource | Name | Purpose |
|----------|------|---------|
| ServiceAccount | `openclaw-oauth-proxy` | SA for OAuth with redirect annotation |
| Secret | `openclaw-oauth-config` | OAuth client-secret + cookie secret |
| Secret | `openclaw-secrets` | Gateway token + provider API keys |
| ConfigMap | `openclaw-config` | `openclaw.json` gateway configuration |
| ConfigMap | `openclaw-agent` | Agent workspace files (HEARTBEAT.md, SOUL.md, etc.) |
| PVC | `openclaw-home-pvc` | 10Gi persistent state (SQLite, agent sessions, logs) |
| Service | `openclaw` | ClusterIP: gateway (18789) + oauth-ui (8443) |
| Route | `openclaw` | TLS edge-terminated route to oauth-proxy |
| Deployment | `openclaw` | Init container + oauth-proxy sidecar + gateway |

## Instance Management

From the installer's **Instances** tab:

| Action | Effect |
|--------|--------|
| **Open** | Opens Route URL with token pre-filled |
| **Re-deploy** | Syncs local agent workspace files + restarts pod |
| **Stop** | Scales replicas to 0 (preserves PVC data) |
| **Start** | Scales replicas back to 1 |
| **Approve Pairing** | Approves pending device pairing requests |

## Rollback Instructions

### Complete Cleanup

To completely remove the OpenClaw deployment and all associated resources:

```bash
# Delete the entire namespace (removes all resources including PVC data)
oc delete project <namespace>
```

> **Warning:** This deletes all data, including agent sessions and SQLite state on the PVC.

### Partial Rollback

To remove specific components while preserving others:

```bash
# Stop the deployment (preserves PVC and config)
oc scale deployment/openclaw --replicas=0 -n <namespace>

# Remove deployment only (preserves PVC, secrets, config)
oc delete deployment openclaw -n <namespace>

# Remove route only (pod keeps running, just not externally accessible)
oc delete route openclaw -n <namespace>
```

### Config Rollback

If a ConfigMap change broke the gateway:

```bash
# Check deployment revision history
oc rollout history deployment/openclaw -n <namespace>

# Roll back to previous revision
oc rollout undo deployment/openclaw -n <namespace>
```

### PVC Data Reset

If the on-disk config is corrupted and the gateway won't start:

```bash
# Scale down, delete PVC, redeploy
oc scale deployment/openclaw --replicas=0 -n <namespace>
oc delete pvc openclaw-home-pvc -n <namespace>

# Re-deploy via installer or re-apply manifests
# The init container will reinitialize the config from the ConfigMap
oc scale deployment/openclaw --replicas=1 -n <namespace>
```

## Appendix

### A. Configuration Parameters

| Parameter | Location | Default | Description |
|-----------|----------|---------|-------------|
| `agents.defaults.model.primary` | ConfigMap | varies | Model reference (e.g., `openai-compat/gpt-oss-20b`) |
| `agents.defaults.heartbeat.every` | ConfigMap | `30m` | Heartbeat interval (`0m` to disable) |
| `gateway.bind` | ConfigMap | `loopback` | Bind address (`loopback` recommended with OAuth proxy) |
| `gateway.controlUi.allowedOrigins` | ConfigMap | `[]` | Route URL for CORS — must match your Route host |
| `models.providers.*.baseUrl` | ConfigMap | none | Model serving endpoint URL |
| `tools.deny` | ConfigMap | `[]` | Tool deny list (e.g., `["group:web", "browser"]`) |
| `OPENCLAW_GATEWAY_TOKEN` | Secret | generated | Gateway auth token (auto-generated by installer) |
| `OPENCLAW_HOME` | Env var | `/data/.openclaw` | Data directory on PVC |

### B. Image Sources

| Component | Registry | Image |
|-----------|----------|-------|
| Gateway | GitHub Container Registry | `ghcr.io/openclaw/openclaw:latest` |
| OAuth Proxy | Red Hat Registry | `registry.redhat.io/openshift4/ose-oauth-proxy:latest` |
| Init Container | Same as gateway | `ghcr.io/openclaw/openclaw:latest` |

### C. Network Ports

| Component | Port | Protocol | Purpose |
|-----------|------|----------|---------|
| Gateway | 18789 | HTTP | API server + Control UI WebSocket |
| OAuth Proxy | 8443 | HTTPS | OAuth-gated frontend |
| Browser Control | 18791 | HTTP | Internal browser automation (loopback only) |

### D. Resource Requirements

| Container | CPU Request | Memory Request | Memory Limit |
|-----------|-------------|----------------|--------------|
| init-config | — | — | 128Mi |
| gateway | 250m | 256Mi | 1Gi |
| oauth-proxy | 100m | 64Mi | 256Mi |

### E. Test Environment Specifications

| Property | Value |
|----------|-------|
| **OpenShift Version** | 4.19.18 |
| **Platform** | AWS (ROSA) |
| **Worker Nodes** | 4 nodes |
| **Storage Class** | gp3-csi (EBS) |
| **Model Endpoint** | vLLM (gpt-oss-20b) on GPU node |
| **Node OS** | Red Hat Enterprise Linux CoreOS |
| **Kernel** | 5.14.0-570.x |

### F. Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| **Single replica only** | No HA — Recreate strategy required because SQLite does not support concurrent writers | Use PostgreSQL-backed model server for multi-replica; or accept single-replica for PoC |
| **NFS incompatible** | SQLite requires POSIX file locking; NFS advisory locks are unreliable | Use block storage (gp3-csi, managed-csi, thin-csi) |
| **Config auto-override** | Gateway may overwrite ConfigMap settings with auto-detected providers on first start | Verify model in logs after every rollout; patch ConfigMap if overridden |
| **Heartbeat on by default** | Fires every 30 min, consumes model API tokens even when idle | Set `agents.defaults.heartbeat.every: "0m"` in ConfigMap |
| **PVC data lost on delete** | Deleting the PVC removes all agent sessions, SQLite state, and logs | Back up PVC data before deletion; consider `Retain` reclaim policy |
| **Device pairing required** | Every new browser session needs a one-time device approval via CLI | Use installer's **Open** action, or approve via `oc exec` |

### G. References

| Resource | URL |
|----------|-----|
| OpenClaw Upstream | <https://github.com/openclaw/openclaw> |
| openclaw-installer | <https://github.com/sallyom/claw-installer> |
| OpenClaw Docs | <https://docs.openclaw.ai> |
| OpenShift Docs | <https://docs.openshift.com> |
| Kustomize | <https://kustomize.io> |
