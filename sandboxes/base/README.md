# OpenShell Base Image

Shared base image for all agent sandbox flavors. Contains system dependencies, user configuration, and the OpenShell entrypoint — no language runtimes or agents.

## What's included

- **Base OS**: UBI 10 minimal (`registry.access.redhat.com/ubi10/ubi-minimal:10.1`)
- **System packages**: ca-certificates, curl, git, jq, iproute, nftables, bind-utils, procps-ng, vim-minimal, tar, gzip, ripgrep
- **Users**: `sandbox` (interactive, GID=0 for OpenShift arbitrary-UID) and `supervisor` (non-login)
- **Directories**: `/sandbox` (home), `/workspace` (working dir), `/etc/openshell/agents/` (install scripts)
- **Policy**: default `policy.yaml` at `/etc/openshell/policy.yaml`
- **Entrypoint**: smart entrypoint that accepts an agent name, installs it if missing, and execs into it

## What's NOT included

No language runtimes (Node.js, Python), no agents, no package managers beyond the OS. These are added by the per-agent flavor images that build on top of this base.

## Build

```bash
podman build --platform linux/amd64 -t openshell-base:latest .
```

Target size: 150-200 MB (currently ~184 MB).

## How flavor images use this

Each agent flavor extends this base with its runtime and agent CLI:

```dockerfile
FROM quay.io/hmoghani/openshell-base:latest

USER 0
RUN microdnf install -y --nodocs nodejs npm && microdnf clean all
RUN npm install -g @openai/codex@0.139.0

USER 1001
WORKDIR /workspace
ENV AGENT_NAME=codex
```

See the flavor Containerfiles under each agent's `deployment/` directory:

- `agents/claude-code/deployment/Containerfile.openshell`
- `agents/codex/deployment/Containerfile.openshell`
- `agents/opencode/deployment/Containerfile.openshell`
- `agents/openclaw/deployment/Containerfile.openshell`

## Registry

Currently published to `quay.io/hmoghani/openshell-base:latest` for development and testing. The production target is `quay.io/redhat-ai/openshell-base`.
