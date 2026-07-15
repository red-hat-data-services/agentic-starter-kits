# OpenCode

## What this agent does

AI-powered terminal-based coding agent built on [OpenCode](https://github.com/sst/opencode). Provides code generation, multi-file editing, code review, and debugging capabilities. Deploys in web mode (OAuth-secured browser UI) or headless CLI mode for terminal sessions and CI pipelines.

## Supported backends

| Backend | Description |
|---------|-------------|
| vLLM | Self-hosted OpenAI-compatible model serving |
| vLLM via OGX | vLLM routed through an OGX gateway |

## Key features

- Two deployment modes: web (OAuth + browser UI) and CLI (headless, `oc exec`)
- Works with any OpenAI-compatible model endpoint
- Session persistence across pod restarts
- MCP server integration for extended tool use
- MLflow tracing support for observability
- Enterprise-ready container image (UBI 9, non-root, restricted-v2 SCC)

## Deployment

For full deployment instructions, see the [deployment guide](../../README.md).
