# Codex — OpenShell Sandbox Deployment

This directory contains an OpenShell-compatible Containerfile for running [OpenAI Codex CLI](https://github.com/openai/codex) inside an OpenShell sandbox.

## Prerequisites

- [Podman](https://podman.io/) or Docker installed
- [OpenShell CLI](https://github.com/NVIDIA/OpenShell-Community) installed
- An OpenShell gateway running

## Build and Run

```bash
podman build --platform linux/amd64 -t codex-sandbox:latest -f Containerfile.openshell .
openshell sandbox create --from codex-sandbox:latest -e OPENAI_API_KEY=sk-...
```

## What `Containerfile.openshell` does

Builds on the shared base image (`quay.io/hmoghani/openshell-base`) which provides the `sandbox` user, system packages, and OpenShell entrypoint. This flavor adds:

- Node.js and npm (from UBI repos)
- Codex CLI via npm (version pinned, Apache 2.0)

## Notes

- OpenShell's supervisor takes over as PID 1 and does not automatically run the Codex CLI. Start it manually inside the sandbox.
- Build with `--platform linux/amd64` when targeting x86_64 clusters from Apple Silicon machines.
- Tested on OpenShell v0.0.58, OpenShift 4.21 (June 2026). Codex CLI version 0.139.0.
