# OpenClaw

## What this agent does

Open-source AI coding assistant with gateway-based model routing and multi-channel support. OpenClaw provides a web-based interface for code generation, editing, and debugging tasks, routing requests through a configurable gateway to any OpenAI-compatible model endpoint.

## Architecture

OpenClaw runs as a single container with a built-in gateway on port 18789. It connects to any vLLM, KServe, or external API endpoint for model serving, and uses persistent storage for session data.

## Key features

- Web-based coding assistant interface
- Gateway-based model routing to any OpenAI-compatible endpoint
- Persistent storage for session and workspace data
- Config-driven deployment (no API keys required by default)

## Deployment

For full deployment instructions, see the [deployment guide](../../deployment/README.md).
