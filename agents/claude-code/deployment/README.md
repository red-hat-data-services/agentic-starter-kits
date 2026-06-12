# Claude Code Deployment Files

This directory contains the Containerfile, entrypoint, and deployment manifests for running Claude Code on OpenShift.

For the full deployment guide, see the [Claude Code on OpenShift README](../README.md).

## Files

| File | Description |
|------|-------------|
| `Containerfile` | Container image build (UBI 10 minimal, Claude Code, MLflow) |
| `entrypoint.sh` | Container entrypoint (auth, MCP, MLflow, skills setup) |
| `deployment.yaml` | Anthropic API deployment (Option A) |
| `deployment-vertex.yaml` | Google Vertex AI deployment (Option B) |
| `deployment-vllm.yaml` | vLLM direct deployment (Option C) |
| `deployment-ogx-vllm.yaml` | vLLM via OGX gateway deployment (Option D) |
