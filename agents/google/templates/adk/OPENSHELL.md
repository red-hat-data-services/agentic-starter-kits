# Google ADK Agent — OpenShell Sandbox Deployment

Run the Google ADK 2.0 agent inside an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox with policy-enforced network isolation, credential management, and filesystem constraints.

This follows the [Bring Your Own Container](https://github.com/NVIDIA/OpenShell/tree/main/examples/bring-your-own-container) pattern: a standard Linux container image with no OpenShell-specific dependencies.

## Prerequisites

- [Podman](https://podman.io/) or Docker installed
- [OpenShell CLI](https://github.com/NVIDIA/OpenShell) v0.1.3+ installed and connected to a gateway
- An OGX-compatible inference endpoint reachable from the sandbox (vLLM, Ollama, Gemini, or remote API)
- Gateway with managed workspace mode and a wildcard service Route (for web UI access via browser)

## Build

```bash
cd agents/google/templates/adk

# Copy repo-level images into build context (playground UI assets)
cp -r ../../../../images ./images
trap 'rm -rf ./images' EXIT

podman build --platform linux/amd64 -t ghcr.io/<your-org>/adk-sandbox:latest -f Containerfile.openshell .
podman push ghcr.io/<your-org>/adk-sandbox:latest
```

Ensure the registry is public so the cluster can pull without imagePullSecrets.

## Run (OpenShell 0.1.3)

### 1. Import the provider profile and create the provider

The provider profile tells OpenShell how to manage the API key. The agent reads `API_KEY` from its environment; OpenShell injects it at runtime so the agent process never sees the raw key value.

```bash
openshell profile import -f openshell-provider.yaml --global

export API_KEY='your-api-key'
openshell provider create --name gemini --type adk-gemini \
  --global-profile --credential API_KEY
unset API_KEY
```

### 2. Create the sandbox

```bash
openshell sandbox create \
  --name adk-agent \
  --from ghcr.io/<your-org>/adk-sandbox:latest \
  --provider gemini \
  --no-auto-providers \
  --policy sandbox-policy-013.yaml \
  --env "MODEL_ID=gemini-2.5-flash" \
  --env "BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/" \
  --detach \
  --restart-policy never \
  -- uvicorn main:app --host 0.0.0.0 --port 8080
```

### 3. Expose the web UI

```bash
openshell service expose adk-agent 8080 web-ui
```

This prints a service URL like:

```text
https://adk-agent--<workspace>--web-ui.<services-domain>/
```

Open it in a browser to access the playground chat UI.

**Note:** The service URL goes through the gateway's passthrough TLS Route. If using a self-signed gateway cert, the browser shows a certificate warning. Accept it once to proceed.

### 4. Verify

```bash
# Health check
openshell sandbox exec adk-agent -- curl -s http://localhost:8080/health
# Expected: {"status":"healthy","agent_initialized":true}

# Chat completion via Route (use the URL from openshell service expose)
curl -sk -X POST <service-url>/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is OpenShift?"}],"stream":false}'
```

## Run (OpenShell 0.0.x — legacy)

For older OpenShell versions without managed workspace mode:

```bash
openshell sandbox create \
  --name adk-agent \
  --from ghcr.io/<your-org>/adk-sandbox:latest \
  --forward 8080 \
  -e API_KEY=your-api-key \
  -e BASE_URL=http://vllm-svc.my-ns.svc.cluster.local:8000/v1 \
  -e MODEL_ID=llama3.1:8b \
  -- uvicorn main:app --host 0.0.0.0 --port 8080
```

`--forward 8080` opens an SSH tunnel so `localhost:8080` on your machine reaches the agent. No service exposure or wildcard Route needed.

## Sandbox Policy

The sandbox policy (`sandbox-policy-013.yaml`) controls:

| Rule | What it allows |
|------|---------------|
| **Filesystem** | `/sandbox` and `/tmp` writable. `/opt`, `/usr`, `/lib` read-only. |
| **LLM endpoint** | `generativelanguage.googleapis.com:443` (change for your endpoint) |
| **All other egress** | **Denied** |

**CRITICAL — UBI9 Python images:** The v0.1.3 supervisor's landlock blocks `/opt/app-root` by default. UBI9 Python images (like this one) store the Python venv there. Without `/opt` in the policy's `read_only` list, Python fails on startup with `PermissionError: pyvenv.cfg`. The provided `sandbox-policy-013.yaml` already includes this fix.

## Provider Profile

The provider profile (`openshell-provider.yaml`) configures:

- **Credential**: `API_KEY` env var, injected by OpenShell at runtime
- **Endpoint**: `generativelanguage.googleapis.com:443` (change for your endpoint)
- **Auth style**: Bearer token in Authorization header

The agent's code reads `API_KEY` from its environment (via `python-dotenv` / `os.getenv`). OpenShell intercepts this and injects the credential from its secure store. The agent process never touches the raw key.

## Gateway Prerequisites (for service exposure)

To access the web UI via a browser (not just `--forward`), the gateway needs:

1. **Wildcard SAN** in `pkiInitJob.serverDnsNames`: `*.openshell-svc.apps.cluster.example.com`
2. **Wildcard Route**: `wildcardPolicy: Subdomain` pointing to the gateway service
3. **WildcardsAllowed** on the ingress controller:

   ```bash
   oc patch ingresscontroller default -n openshift-ingress-operator \
     --type merge -p '{"spec":{"routeAdmission":{"wildcardPolicy":"WildcardsAllowed"}}}'
   ```

Without these, use `--forward 8080` for local access instead.

## How It Works

| Aspect | Standard (Helm) | OpenShell 0.1.3 Sandbox |
|--------|----------------|------------------------|
| Base image | UBI9 Python 3.12 | Same |
| Network isolation | K8s NetworkPolicy | OpenShell L7 policy engine (per-binary, per-endpoint) |
| Credential injection | Helm secrets / env vars | OpenShell providers (agent never sees raw key) |
| Process supervision | Container runtime PID 1 | OpenShell supervisor (landlock + namespace isolation) |
| Start command | Dockerfile CMD | Explicit `-- <command>` |
| Web UI access | OpenShift Route | `openshell service expose` via gateway wildcard Route |

## Files

| File | Purpose |
|------|---------|
| `Containerfile.openshell` | Build the sandbox image |
| `sandbox-policy-013.yaml` | OpenShell 0.1.3+ sandbox policy |
| `openshell-provider.yaml` | Provider profile for LLM credential management |
| `OPENSHELL.md` | This file |

## Cleanup

```bash
openshell service delete adk-agent web-ui
openshell sandbox delete adk-agent
```

## Tested On

| Component | Version |
|-----------|---------|
| OpenShell Gateway | 0.1.3 |
| OpenShell CLI | 0.1.3 |
| OpenShift | 4.20.33 |
| Google ADK | 2.1.0 |
| Gemini | 2.5 Flash |
