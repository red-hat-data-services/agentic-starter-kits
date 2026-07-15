# Troubleshooting

Common issues and solutions for OpenClaw on OpenShift. Issues are listed from most to least frequently encountered.

## Table of Contents

- [Route returns "Application is not available" (503)](#route-returns-application-is-not-available-503)
- [Gateway uses wrong model / "No API key" errors](#gateway-uses-wrong-model--no-api-key-errors)
- [Heartbeat flooding the chat UI](#heartbeat-flooding-the-chat-ui)
- [Device pairing required after SSO login](#device-pairing-required-after-sso-login)
- [Pod stuck in CrashLoopBackOff](#pod-stuck-in-crashloopbackoff)
- [Config clobbered on restart](#config-clobbered-on-restart)
- [Device pairing rate limiter](#device-pairing-rate-limiter)
- [Diagnostic commands](#diagnostic-commands)

---

## Route returns "Application is not available" (503)

**Severity:** Blocking — users cannot access the UI.

**Cause:** The oauth-proxy uses `--http-address` (plain HTTP) by default. If the Route has `tls.termination: reencrypt`, the router expects TLS on the backend and the connection fails silently.

**Symptoms:**

```text
Browser: "Application is not available"
curl returns: 503
```

**Fix:** Recreate the Route with `edge` termination:

```bash
oc delete route openclaw -n <namespace>

cat <<'EOF' | oc apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: openclaw
  namespace: <namespace>
  labels:
    app: openclaw
  annotations:
    haproxy.router.openshift.io/timeout: 30m
spec:
  to:
    kind: Service
    name: openclaw
    weight: 100
  port:
    targetPort: oauth-ui
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF
```

**Verification:**

```bash
curl -s -o /dev/null -w "%{http_code}" -k https://<route-url>
```

Expected output:

```text
403
```

> A `403` is correct — it means the OAuth proxy is running and will redirect to OpenShift SSO. A `503` means the Route is still misconfigured.

**Prevention:** When deploying via the installer, verify the Route TLS mode immediately after deployment:

```bash
oc get route openclaw -n <namespace> -o jsonpath='{.spec.tls.termination}'
# Should show: edge
```

---

## Gateway uses wrong model / "No API key" errors

**Severity:** Blocking — agent cannot respond to messages.

**Cause:** OpenClaw auto-generates its config on first start. If the gateway detects a provider (e.g., Anthropic) it will override the ConfigMap settings with its own defaults. This means the ConfigMap says vLLM but the gateway is actually trying to use Anthropic.

**Symptoms in logs:**

```text
No API key found for provider "anthropic"
model fallback decision: decision=candidate_failed requested=anthropic/claude-sonnet-4-6
```

**Symptoms in UI:** The model selector in the Control UI shows a model name you did not configure (e.g., `gpt-oss-20b` instead of `gemini-2.5-pro`).

**Fix:** Patch the ConfigMap with the correct model provider config, then restart:

```bash
# Export current config
oc get configmap openclaw-config -n <namespace> \
  -o jsonpath='{.data.openclaw\.json}' > /tmp/openclaw-config.json

# Edit /tmp/openclaw-config.json:
# - Set agents.defaults.model.primary to "openai-compat/gpt-oss-20b"
# - Add models.providers.openai-compat with your vLLM endpoint

# Apply and restart
oc create configmap openclaw-config \
  --from-file=openclaw.json=/tmp/openclaw-config.json \
  -n <namespace> --dry-run=client -o yaml | oc apply -f -
oc rollout restart deployment/openclaw -n <namespace>
```

**Verification:**

```bash
oc logs deployment/openclaw -c gateway -n <namespace> | grep "agent model"
```

Expected output:

```text
[gateway] agent model: openai-compat/gpt-oss-20b
```

**Prevention:** Always check the gateway logs after every rollout to confirm the model matches your intent.

---

## Heartbeat flooding the chat UI

**Severity:** Moderate — consumes API tokens and clutters the chat history.

**Cause:** OpenClaw's heartbeat scheduler fires every 30 minutes by default, sending `HEARTBEAT_OK` messages to the chat. If the model provider is misconfigured, each heartbeat triggers an error instead, producing dozens of error messages per day.

**Symptoms in UI:** Repeated "HEARTBEAT_OK" messages or "Agent failed before reply" errors every 30 minutes.

**Symptoms in logs:**

```text
[heartbeat] started
```

**Fix:** Set `heartbeat.every` to `"0m"` in the ConfigMap:

```bash
# Export config
oc get configmap openclaw-config -n <namespace> \
  -o jsonpath='{.data.openclaw\.json}' > /tmp/openclaw-config.json

# Add to agents.defaults:
#   "heartbeat": { "every": "0m" }
# Also add to each agent in agents.list:
#   "heartbeat": { "every": "0m" }

# Apply and restart
oc create configmap openclaw-config \
  --from-file=openclaw.json=/tmp/openclaw-config.json \
  -n <namespace> --dry-run=client -o yaml | oc apply -f -
oc rollout restart deployment/openclaw -n <namespace>
```

**Verification:**

```bash
oc logs deployment/openclaw -c gateway -n <namespace> | grep heartbeat
```

Expected output:

```text
[heartbeat] disabled
```

**Reference:** See [OpenClaw heartbeat docs](https://docs.openclaw.ai/gateway/heartbeat) for advanced options (`activeHours`, `target`, `lightContext`).

---

## Device pairing required after SSO login

**Severity:** Low — one-time setup per browser.

**Cause:** The Control UI browser session needs a one-time device approval, even after OpenShift OAuth login. This is an OpenClaw security feature, not an OpenShift issue.

**Fix:**

```bash
# Get the request ID from the UI prompt, then:
oc exec deployment/openclaw -n <namespace> -c gateway -- \
  openclaw devices approve <request-id>
```

Expected output:

```text
Device approved: <request-id>
```

Alternatively, use the **Open** action from the installer's **Instances** tab — it opens with the token pre-filled and may auto-pair.

---

## Pod stuck in CrashLoopBackOff

**Severity:** Blocking — gateway is down.

**Cause:** OpenClaw auto-generates config at startup. If the config on the PVC conflicts with the ConfigMap, the gateway detects a change, overwrites the file, and triggers a process restart that kills PID 1.

**Diagnostic:**

```bash
oc describe pod -l app=openclaw -n <namespace> | grep -A 5 "Last State"
oc logs deployment/openclaw -c gateway -n <namespace> --previous
```

Look for: `Config overwrite` or `Config observe anomaly` messages.

**Fix:** Delete the PVC data and redeploy:

```bash
oc scale deployment/openclaw --replicas=0 -n <namespace>
oc delete pvc openclaw-state -n <namespace>
# If deployed via claw-installer, the PVC is named openclaw-home-pvc instead
# Redeploy via installer or re-apply manifests
oc scale deployment/openclaw --replicas=1 -n <namespace>
```

> **Warning:** This deletes all agent sessions and chat history. Back up the PVC first if needed:
>
> ```bash
> oc cp <pod-name>:/data/.openclaw /tmp/openclaw-backup -c gateway -n <namespace>
> ```

---

## Config clobbered on restart

**Severity:** Moderate — settings revert unexpectedly.

**Cause:** OpenClaw's init container copies `openclaw.json` from the ConfigMap to the PVC on every pod start. However, the gateway also writes back to the same file at runtime (model discovery, plugin state). On the next restart, the init container overwrites these runtime changes with the original ConfigMap version. This produces `.clobbered.*` backup files on the PVC.

**Symptoms:**

```bash
oc exec deployment/openclaw -c gateway -n <namespace> -- ls /home/node/.openclaw/
# Shows: openclaw.json.clobbered.2026-04-15T14-45-55-777Z
```

**Fix:** Update the ConfigMap to include any runtime changes you want to preserve:

```bash
# Export the running config (not the ConfigMap)
oc exec deployment/openclaw -c gateway -n <namespace> -- \
  cat /home/node/.openclaw/openclaw.json > /tmp/openclaw-config.json

# Review and apply
oc create configmap openclaw-config \
  --from-file=openclaw.json=/tmp/openclaw-config.json \
  -n <namespace> --dry-run=client -o yaml | oc apply -f -
```

---

## Device Pairing Rate Limiter

**Severity:** Blocking — browser cannot connect even with valid credentials.

**Cause:** When a browser repeatedly sends a stale device token (e.g., after PVC data was deleted and device pairings were cleared), the gateway's in-memory rate limiter kicks in after several failed attempts. Once rate-limited, all connection attempts from that client are rejected — even after fixing the underlying token issue.

**Symptoms in logs:**

```text
unauthorized ... reason=device_token_mismatch
unauthorized ... reason=rate_limited
```

**Symptoms in browser:** "Too many failed authentication attempts (retry later)" or the connection silently fails.

**Fix (both steps required):**

1. **Clear browser site data** for the OpenClaw route URL — this removes the cached stale device token:
   - Chrome: Click lock icon in URL bar → "Site settings" → "Clear data"
   - Or: DevTools (F12) → Application → Storage → "Clear site data"

2. **Restart the pod** to reset the in-memory rate limiter:

   ```bash
   oc rollout restart deployment/openclaw -n <namespace>
   ```

3. **Refresh the browser** — you should now see a fresh device pairing prompt. Approve it:

   ```bash
   oc exec deployment/openclaw -c gateway -n <namespace> -- \
     openclaw devices approve <request-id>
   ```

**Verification:** The browser connects and shows the chat UI without errors.

**Prevention:** When clearing device pairings (`openclaw devices clear`), always clear browser site data at the same time to prevent the stale token retry loop.

---

## Diagnostic Commands

```bash
# Pod status
oc get pods -n <namespace>

# Gateway logs (tail)
oc logs deployment/openclaw -c gateway -n <namespace> --tail=50

# Gateway logs (full)
oc logs deployment/openclaw -c gateway -n <namespace>

# OAuth proxy logs
oc logs deployment/openclaw -c oauth-proxy -n <namespace>

# Previous pod logs (after crash)
oc logs deployment/openclaw -c gateway -n <namespace> --previous

# Check route config
oc get route openclaw -n <namespace> -o jsonpath='{.spec.tls.termination}'

# Check what model is active
oc logs deployment/openclaw -c gateway -n <namespace> | grep "agent model"

# Check ConfigMap vs on-disk config
oc get configmap openclaw-config -n <namespace> \
  -o jsonpath='{.data.openclaw\.json}' | python3 -m json.tool

# Check on-disk config (what gateway is actually using)
oc exec deployment/openclaw -c gateway -n <namespace> -- \
  cat /home/node/.openclaw/openclaw.json | python3 -m json.tool

# List clobbered config backups
oc exec deployment/openclaw -c gateway -n <namespace> -- \
  ls -la /home/node/.openclaw/openclaw.json.clobbered.* 2>/dev/null

# Check PVC status
oc get pvc -n <namespace>

# Check deployment events
oc describe deployment openclaw -n <namespace> | tail -20

# Exec into the gateway
oc exec -it deployment/openclaw -c gateway -n <namespace> -- sh
```
