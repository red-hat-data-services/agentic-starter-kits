# OpenClaw

## What this agent does

Open-source AI coding assistant built on [OpenClaw](https://github.com/openclaw/openclaw) with gateway-based model routing. Provides a web-based interface for code generation, editing, and debugging, routing requests through a built-in gateway to any OpenAI-compatible model endpoint.

## Supported backends

| Backend | Description |
|---------|-------------|
| vLLM | Self-hosted OpenAI-compatible model serving |
| vLLM via OGX | vLLM routed through an OGX gateway |

## Key features

- Web-based coding assistant with built-in gateway (port 18789)
- Gateway-based model routing to any OpenAI-compatible endpoint
- Persistent storage for session and workspace data
- Config-driven deployment via kustomize overlays
- MLflow tracing support via OTel collector sidecar
- OpenShell sandbox mode for experimentation

## Deployment

For full deployment instructions, see the [deployment guide](../../deployment/README.md).
