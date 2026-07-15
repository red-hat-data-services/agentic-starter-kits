# Claude Code

## What this agent does

Anthropic's Claude Code CLI running as a containerized coding agent. Provides AI-powered code generation, editing, debugging, and repository exploration through a terminal interface. Supports multi-file edits, git operations, and MCP tool integration.

## Supported backends

| Backend | Description |
|---------|-------------|
| Anthropic API | Direct access via API key |
| Google Vertex AI | GCP-managed Claude endpoints |
| vLLM | Self-hosted OpenAI-compatible model serving |
| vLLM via OGX | vLLM routed through an OGX gateway |

## Key features

- Interactive terminal-based coding assistant
- Multi-file code generation and refactoring
- Git-aware operations (commit, diff, blame)
- MCP server integration for extended tool use
- MLflow tracing support for observability

## Deployment

For full deployment instructions, see the [deployment guide](../../README.md).
