# OpenCode A2A Agent Deployment

This directory contains a reference implementation for deploying [OpenCode](https://opencode.ai) as an A2A agent using the Agent-to-Agent (A2A) protocol.

## Overview

OpenCode is an AI-powered coding assistant. This implementation wraps OpenCode with an A2A agent card server to enable:

- **Service discovery** via A2A agent card endpoint
- **Standardized configuration** using LLM_* environment variables
- **Multi-provider support** (direct vLLM, OGX, OpenAI, etc.)

## Architecture

```text
┌──────────────────────────────────────────────┐
│  Container (port 8000)                       │
│                                              │
│  ┌───────────────────────────────────────┐   │
│  │ opencode-a2a (FastAPI)                │   │
│  │ - Serves /.well-known/agent-card.json │   │
│  │ - Proxies /health from opencode serve │   │
│  └──────────────┬────────────────────────┘   │
│                 │ http://localhost:4096      │
│  ┌──────────────▼────────────────────────┐   │
│  │ opencode serve (port 4096)            │   │
│  │ - OpenCode HTTP API                   │   │
│  │ - Configured via ~/.config/opencode/  │   │
│  └──────────────┬────────────────────────┘   │
│                 │                            │
└─────────────────┼────────────────────────────┘
                  │
                  ▼
          LLM_API_BASE (vLLM, OGX, etc.)
```

### Components

1. **Base Image**: `quay.io/opendatahub/odh-opencode-rhel9:latest`
   - Pre-built OpenCode container from Red Hat OpenShift AI

2. **opencode-a2a Server** (`Containerfile.a2a`)
   - Installed from `agent-servers` repo (opencode subdirectory)
   - Serves A2A agent card for discovery
   - Proxies health checks from OpenCode

3. **Entrypoint Script** (`entrypoint-a2a.sh`)
   - Translates LLM_* env vars to OpenCode config
   - Starts both `opencode serve` and `opencode-a2a` processes

4. **Kubernetes Template** (`opencode-a2a-template.yaml`)
   - OpenShift Template for deployment
   - Supports multiple deployment variants (direct vLLM, OGX, OpenAI, etc.)

## Environment Variables

The deployment uses the following LLM configuration variables:

| Variable           | Description                                              | Required | Default    |
|--------------------|----------------------------------------------------------|----------|------------|
| `LLM_PROVIDER`     | Provider name (vllm, ogx, openai, etc.)                  | No       | `vllm`     |
| `LLM_API_BASE`     | LLM API endpoint (e.g., `https://api.openai.com/v1`)     | Yes      | -          |
| `LLM_MODEL`        | Model identifier (e.g., `gpt-4o`, `gpt-oss-120b`)        | Yes      | -          |
| `LLM_API_KEY`      | API key for the LLM provider                             | No       | -          |
| `A2A_PORT`         | Port for A2A server                                      | No       | `8000`     |
| `A2A_PROVIDER_ORG` | Organization name in agent card                          | No       | `Red Hat`  |

### Provider-Specific Model Naming

- **Direct vLLM**: Use model name only (e.g., `LLM_MODEL=gpt-oss-120b`)
- **Through OGX**: Use provider/model format (e.g., `LLM_MODEL=vllm/gpt-oss-120b`)
- **OpenAI**: Use OpenAI model names (e.g., `LLM_MODEL=gpt-4o`)

## Deployment

### Prerequisites

- OpenShift/Kubernetes cluster
- LLM endpoint accessible from the cluster
- Secret containing LLM API key (if required)

### Build Container Image

Using OpenShift BuildConfig (recommended for OpenShift deployments):

```bash
cd agents/opencode/deployment

# Create ImageStream to store the built image
oc create imagestream opencode-a2a -n your-namespace

# Create BuildConfig for binary builds
cat <<EOF | oc apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: opencode-a2a
  namespace: your-namespace
spec:
  output:
    to:
      kind: ImageStreamTag
      name: opencode-a2a:latest
  source:
    type: Binary
  strategy:
    dockerStrategy:
      dockerfilePath: Containerfile.a2a
    type: Docker
EOF

# Trigger build from current directory
oc start-build opencode-a2a --from-dir=. --follow -n your-namespace

# The image will be available at:
# image-registry.openshift-image-registry.svc:5000/your-namespace/opencode-a2a:latest
```

Alternative: Using podman/docker (for testing or non-OpenShift environments):

```bash
cd agents/opencode/deployment

# Build for amd64
podman build --platform linux/amd64 \
  -t opencode-a2a:latest \
  -f Containerfile.a2a .

# Tag for your registry
podman tag opencode-a2a:latest \
  your-registry.example.com/your-namespace/opencode-a2a:latest

# Push to registry
podman push your-registry.example.com/your-namespace/opencode-a2a:latest
```

### Deploy to OpenShift

#### Option 1: Direct vLLM Connection

```bash
# Create secret with API key (if needed)
oc create secret generic opencode-model-credentials \
  --from-literal=api-key="your-api-key" \
  -n your-namespace

# Deploy using template
oc process -f opencode-a2a-template.yaml \
  -p NAMESPACE=your-namespace \
  -p IMAGE=image-registry.openshift-image-registry.svc:5000/your-namespace/opencode-a2a:latest \
  -p LLM_PROVIDER=vllm \
  -p LLM_API_BASE=http://vllm-service.namespace.svc.cluster.local:8000/v1 \
  -p LLM_MODEL=gpt-oss-120b \
  | oc apply -f -
```

#### Option 2: Through OGX

```bash
oc process -f opencode-a2a-template.yaml \
  -p NAMESPACE=your-namespace \
  -p IMAGE=image-registry.openshift-image-registry.svc:5000/your-namespace/opencode-a2a:latest \
  -p LLM_PROVIDER=ogx \
  -p LLM_API_BASE=http://ogx-service.namespace.svc.cluster.local:8321/v1 \
  -p LLM_MODEL=vllm/gpt-oss-120b \
  | oc apply -f -
```

Note: OGX namespaces models by provider, so use `provider/model` format.

#### Option 3: OpenAI API

```bash
oc process -f opencode-a2a-template.yaml \
  -p NAMESPACE=your-namespace \
  -p IMAGE=image-registry.openshift-image-registry.svc:5000/your-namespace/opencode-a2a:latest \
  -p LLM_PROVIDER=openai \
  -p LLM_API_BASE=https://api.openai.com/v1 \
  -p LLM_MODEL=gpt-4o \
  -p LLM_API_KEY_SECRET=openai-api-key \
  | oc apply -f -
```

## Verification

### Check Deployment Status

```bash
# Check deployment is running
oc get deployment opencode-a2a -n your-namespace

# Check pod status
oc get pods -n your-namespace -l app.kubernetes.io/name=opencode-a2a
```

### Test Agent Card Endpoint

```bash
# From within the pod
oc exec -n your-namespace deployment/opencode-a2a -- \
  curl -s http://localhost:8000/.well-known/agent-card.json | jq .

# From another pod in cluster
oc run -it --rm debug --image=curlimages/curl -- \
  curl -s http://opencode-a2a.your-namespace.svc.cluster.local:8000/.well-known/agent-card.json
```

### Verify OpenCode Configuration

```bash
# Exec into pod
oc exec -it -n your-namespace deployment/opencode-a2a -- /bin/bash

# Check generated OpenCode config
cat ~/.config/opencode/opencode.json

# Should show provider configuration:
# {
#   "$schema": "https://opencode.ai/config.json",
#   "provider": {
#     "vllm": {
#       "npm": "@ai-sdk/openai-compatible",
#       "name": "vllm",
#       "options": {
#         "baseURL": "http://vllm:8000/v1",
#         "apiKey": ""
#       },
#       "models": {
#         "gpt-oss-120b": {
#           "name": "gpt-oss-120b"
#         }
#       }
#     }
#   },
#   "model": "vllm/gpt-oss-120b",
#   ...
# }
```

### Test OpenCode TUI Attachment

```bash
# Exec into pod and attach to OpenCode TUI
oc exec -it -n your-namespace deployment/opencode-a2a -- /bin/bash

# Inside pod:
opencode attach http://localhost:4096

# You should see the OpenCode TUI interface
# Try sending a message to verify LLM connectivity
```

### Verify LLM Traffic

Monitor logs to confirm requests reach the LLM:

```bash
# OpenCode pod logs
oc logs -n your-namespace deployment/opencode-a2a --tail=50

# vLLM logs (if direct connection)
oc logs -n vllm-namespace deployment/vllm --tail=50

# OGX logs (if using OGX)
oc logs -n ogx-namespace deployment/ogx --tail=50
```

## Configuration Details

### How Environment Variables are Translated

The `entrypoint-a2a.sh` script performs the following translation:

```bash
# Input:
LLM_PROVIDER=vllm
LLM_API_BASE=http://vllm:8000/v1
LLM_MODEL=gpt-oss-120b
LLM_API_KEY=secret-key

# Output (OpenCode config at ~/.config/opencode/opencode.json):
{
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vllm",
      "options": {
        "baseURL": "http://vllm:8000/v1",
        "apiKey": "secret-key"
      },
      "models": {
        "gpt-oss-120b": {
          "name": "gpt-oss-120b"
        }
      }
    }
  },
  "model": "vllm/gpt-oss-120b",
  "small_model": "vllm/gpt-oss-120b",
  "enabled_providers": ["vllm"]
}
```

This approach allows:

- **Standardization**: Use consistent naming across all agents
- **Flexibility**: Support any OpenAI-compatible provider
- **Runtime configuration**: No image rebuilds for different providers

## Known Limitations

### A2A Protocol Execution Not Implemented

**Current state (RHAIENG-5825 ✅):**

- Agent card server is implemented and running
- Agent card is accessible at `/.well-known/agent-card.json`
- Health checks are proxied
- Configuration is correctly generated

**Not yet implemented (RHAIENG-5826 ⏳):**

- A2A task execution endpoint (`POST /v1/agent/tasks`)
- Request proxying from A2A client to OpenCode
- Streaming response support
- State management

**Current behavior:**

- Agent card endpoint is accessible ✅
- Direct OpenCode TUI access works ✅

The full A2A protocol implementation is tracked in **RHAIENG-5826** and will enable end-to-end agent execution.

### OpenCode TUI Access

Users can bypass the A2A protocol limitation by exec'ing into the pod and using OpenCode's TUI directly:

```bash
oc exec -it -n your-namespace deployment/opencode-a2a -- opencode attach http://localhost:4096
```

## Files Reference

| File                  | Purpose                                                       |
|-----------------------|---------------------------------------------------------------|
| `Containerfile.a2a`   | Extends base OpenCode image with opencode-a2a server          |
| `entrypoint-a2a.sh`   | Entrypoint that configures OpenCode and runs both servers     |
| `opencode-a2a-template.yaml` | OpenShift Template for A2A deployment                   |
| `README-a2a.md`       | This file - deployment and usage guide                        |

## Related Work

- **agent-servers repo**: Source for opencode-a2a Python package
  - Installation: `pip install 'opencode-a2a @ git+https://github.com/red-hat-data-services/agent-servers.git#subdirectory=opencode'`

- **OpenCode**: AI coding assistant
  - Project: <https://opencode.ai>
  - Supports multiple LLM providers via Vercel AI SDK

## Troubleshooting

### OpenCode can't reach LLM

Verify LLM_API_BASE is correct:

```bash
oc exec -n your-namespace deployment/opencode-a2a -- \
  sh -c 'curl -s $LLM_API_BASE/models'
```

Check OpenCode config was generated:

```bash
oc exec -n your-namespace deployment/opencode-a2a -- \
  cat ~/.config/opencode/opencode.json
```

Test from OpenCode TUI to see detailed errors:

```bash
oc exec -it -n your-namespace deployment/opencode-a2a -- \
  opencode attach http://localhost:4096
```

### Image pull errors

Ensure you're using the correct image path:

```bash
# Check deployment image
oc get deployment opencode-a2a -n your-namespace -o jsonpath='{.spec.template.spec.containers[0].image}'

# If wrong, update it
oc set image deployment/opencode-a2a -n your-namespace \
  opencode-a2a=image-registry.openshift-image-registry.svc:5000/your-namespace/opencode-a2a:latest
```

### Pod crashes or restarts

Check logs for startup errors:

```bash
oc logs -n your-namespace deployment/opencode-a2a --previous
```

Common issues:

- Missing LLM_API_BASE: Pod fails to start with validation error (required when LLM_MODEL is set)
- Invalid LLM_API_BASE: OpenCode serve starts but can't reach LLM
- Missing secret: Pod fails to start if `LLM_API_KEY_SECRET` doesn't exist
