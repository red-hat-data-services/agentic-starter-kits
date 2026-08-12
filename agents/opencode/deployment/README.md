# OpenCode Deployment Files

This directory contains the Containerfiles, entrypoints, and deployment manifests for running OpenCode on OpenShift.

For the full deployment guide, see the [OpenCode on RHOAI README](../README.md).

## Files

| File | Description |
|------|-------------|
| `manifests/` | Base kustomize manifests (web mode + OAuth proxy) |
| `overlays/cli/` | CLI mode overlay (headless, no OAuth, `oc exec`) |
| `overlays/example/` | Template for custom environments |
| `overlays/mlflow-tracing/` | MLflow tracing overlay |
| `Containerfile.openshell` | OpenShell sandbox image variant |
| `Containerfile.openshell-mlflow` | OpenShell sandbox + MLflow tracing variant |
| `Containerfile.mlflow` | MLflow tracing image variant (kustomize deployment) |
| `Containerfile.a2a` | A2A agent card discovery variant |
| `entrypoint-a2a.sh` | Entrypoint for A2A variant (runs opencode serve + opencode-a2a) |
| `opencode-a2a-template.yaml` | OpenShift Template for A2A deployment |
| `DEPLOYMENT.md` | Legacy deployment guide (content moved to `../README.md`) |
| `README-a2a.md` | A2A deployment guide |
| `docs/` | MLflow tracing schema, benchmarks, and screenshots |
