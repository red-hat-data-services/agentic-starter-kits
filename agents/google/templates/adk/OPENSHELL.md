# Google ADK Agent — OpenShell Sandbox Deployment

Run the Google ADK 2.0 agent inside an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox with policy-enforced network isolation and filesystem constraints.

This follows the [Bring Your Own Container](https://github.com/NVIDIA/OpenShell/tree/main/examples/bring-your-own-container) pattern: a standard Linux container image with no OpenShell-specific dependencies.

## Prerequisites

- [Podman](https://podman.io/) or Docker installed
- [OpenShell CLI](https://github.com/NVIDIA/OpenShell) installed and connected to a gateway
- An OGX-compatible inference endpoint reachable from the sandbox (vLLM, Ollama, or remote API)

## Build

```bash
cd agents/google/templates/adk

# Copy repo-level images into build context (playground UI assets)
cp -r ../../../../images ./images
trap 'rm -rf ./images' EXIT

podman build --platform linux/amd64 -t quay.io/<your-org>/adk-sandbox:latest -f Containerfile.openshell .
podman push quay.io/<your-org>/adk-sandbox:latest
```

Ensure the quay.io repository is public so the cluster can pull without imagePullSecrets.

## Run

OpenShell's sandbox supervisor replaces the image's CMD/ENTRYPOINT at runtime. You **must** pass the application start command explicitly after `--`:

```bash
openshell sandbox create \
  --name adk-agent \
  --from quay.io/<your-org>/adk-sandbox:latest \
  --forward 8080 \
  -e API_KEY=not-needed-for-local \
  -e BASE_URL=http://vllm-svc.my-ns.svc.cluster.local:8000/v1 \
  -e MODEL_ID=llama3.1:8b \
  -- uvicorn main:app --host 0.0.0.0 --port 8080
```

Flags:

- `--forward 8080` opens an SSH tunnel so `localhost:8080` on your machine reaches the agent inside the sandbox
- `-e` injects environment variables via OpenShell providers (never written to disk)
- `-- <command>` is the process the supervisor executes via SSH once the sandbox is ready

## Verify

```bash
# Health check (should return {"status": "healthy", "agent_initialized": true})
curl -s http://localhost:8080/health | python3 -m json.tool

# Chat completion
curl -s -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is OpenShift?"}],"stream":false}' \
  | python3 -m json.tool
```

## Network Policy

The ADK agent only needs outbound access to the configured LLM endpoint. Apply a restrictive policy:

```yaml
sandbox:
  network:
    egress:
      - host: "vllm-svc.my-ns.svc.cluster.local"
        port: 8000
        methods: ["POST"]
        paths:
          - "/v1/chat/completions"
          - "/v1/completions"
```

```bash
openshell policy set adk-agent --policy policy.yaml --wait
```

## Cleanup

```bash
openshell sandbox delete adk-agent
```

## How It Works

OpenShell isolates the sandbox container and routes all outbound traffic through its policy engine. The ADK agent runs as a normal FastAPI/uvicorn process inside the container — no code changes required. The key differences from a standard Helm deployment:

| Aspect | Standard (Helm) | OpenShell Sandbox |
|--------|----------------|-------------------|
| Base image | UBI9 Python 3.12 | Same (UBI9 Python 3.12) |
| Network isolation | K8s NetworkPolicy | OpenShell L7 policy engine |
| Credential injection | Helm secrets / env vars | OpenShell providers (`-e` flags) |
| Process supervision | Container runtime PID 1 | OpenShell supervisor via SSH |
| Start command | Dockerfile CMD | Explicit `-- <command>` |

## Notes

- The ADK agent is a long-running FastAPI server. Unlike CLI agents (Claude Code, Codex), it does not need interactive terminal access.
- `BASE_URL` must be reachable from within the sandbox. Use cluster-internal DNS for in-cluster endpoints.
- If the model endpoint is unreachable, `/health` still returns healthy but `/chat/completions` will fail with a 500.
- Build with `--platform linux/amd64` when targeting x86_64 clusters from Apple Silicon machines.
