# EvalHub Server/SDK Compatibility Issue — RHOAI 3.4.0-ea.2

## Environment

- **RHOAI**: `3.4.0-ea.2` (rhods-operator, beta channel, redhat-operators catalog)
- **TrustyAI Operator**: shipped with 3.4.0-ea.2
- **Cluster**: ROSA HCP, OpenShift 4.x

## Shipped EvalHub Server Image

| Field | Value |
|---|---|
| Image | `registry.redhat.io/rhoai/odh-eval-hub-rhel9@sha256:c27bfe0140b8072993f09925f5c78bb8cefb6d5adbb9bc4c772e2b0f108a9422` |
| Image label | `version=v3.4.0-ea.2`, `build-date=2026-04-15` |
| Git commit | `d0b5cda875c80bb309a9d673c9cabfbbc958cc1a` (from `github.com/red-hat-data-services/eval-hub`) |
| Actual server version | `0.2.0` (from `VERSION` file at that commit) |
| Health endpoint reports | `"build":"0.0.1"` — `BUILD_NUMBER` arg not injected during Red Hat build |

## SDK/CLI

- **Latest published**: `eval-hub-sdk==0.1.6` (PyPI)
- **Used by agentic-starter-kits**: `eval-hub-sdk[adapter]>=0.1.4,<0.2` (in Containerfile and pyproject.toml)

## Compatibility Matrix

From `eval-hub/eval-hub` COMPATIBILITY.md — only one verified pair exists:

| EvalHub Server | SDK | RHOAI |
|---|---|---|
| 0.1.0 | 0.1.0a8 | 3.4-ea1 |

Neither artifact is usable today: the `0.1.0` image tag was cleaned up from quay.io, and SDK `0.1.0a8` has no CLI entry point (CLI was added in `0.1.3`).

## Issues Found (server `0.2.0` + SDK `0.1.6`)

### 1. REST-registered providers not found at job execution time

- SDK registers a custom BYOF provider via `POST /api/v1/evaluations/providers` — returns 201 with provider ID
- When the job runs, the k8s runtime fails with `provider "<id>" not found`
- **Root cause**: the `0.2.0` server's k8s runtime lookup path doesn't find tenant-scoped, REST-registered providers
- **Impact**: The entire BYOF adapter pattern (the primary custom eval integration point) is broken on the shipped image
- **Fix**: Works correctly on server `0.3.0`

### 2. `evalhub providers list` crashes on built-in providers

- The operator deploys built-in providers (garak, guidellm, etc.) that return `"tags": null` in their benchmark definitions
- SDK `0.1.4`–`0.1.6` Pydantic models require `tags` to be a list, causing `ValidationError`
- **Impact**: CLI crashes on `providers list`; E2E scripts fail unless guarded with `|| true`

### 3. Health endpoint reports wrong version

- Server reports `"build":"0.0.1"` instead of `0.2.0`
- The Red Hat Containerfile doesn't pass `BUILD_NUMBER` to the Go build, so it falls back to the hardcoded default in `main.go`
- **Impact**: Users cannot determine what server version they're running; debugging version mismatches is impossible without inspecting image labels via `skopeo`

### 4. Sidecar image config field changed between versions

- Server `0.2.0` reads sidecar image from `service.eval_sidecar_image` in config.yaml
- Server `0.3.0` reads from `sidecar.sidecar_container.image`
- The operator-generated ConfigMap uses `service.eval_sidecar_image`, which `0.3.0` ignores, falling back to the hardcoded default `eval-runtime-sidecar:latest` (not a valid public image)
- **Impact**: If the server image is updated to `0.3.0` without also updating the ConfigMap, job pods fail with `ImagePullBackOff`

### 5. MLflow `TRACKING_INSECURE_TLS` + `TRACKING_SERVER_CERT_PATH` conflict

- The operator injects `MLFLOW_TRACKING_SERVER_CERT_PATH` (service CA cert) into adapter pods
- If the E2E script also sets `MLFLOW_TRACKING_INSECURE_TLS=true` in the provider env, the MLflow Python client raises: `When 'ignore_tls_verification' is true then 'server_cert_path' must not be set!`
- **Impact**: MLflow trace enrichment and run logging fail silently; `mlflow_run_id` is null in results

## Workaround Applied

1. Scaled down TrustyAI operator (`--replicas=0`)
2. Replaced EvalHub deployment image with `quay.io/evalhub/evalhub:0.3.0`
3. Patched `evalhub-config` ConfigMap to add `sidecar.sidecar_container.image: quay.io/evalhub/evalhub:0.3.0`
4. Added `EVALHUB_ALLOW_LOCALHOST=true` to provider env (adapter validates `mlflow_tracking_uri` and blocks localhost, which the sidecar proxy uses)
5. Set `MLFLOW_TRACKING_URI` on EvalHub deployment to include `/mlflow` subpath (RHOAI MLflow serves under `/mlflow/`)
6. Removed `MLFLOW_TRACKING_INSECURE_TLS` from provider env to avoid conflict with operator-injected cert path

## Recommendations

1. **Ship EvalHub server `0.3.0`** (or later) in the next RHOAI build — it fixes the REST-registered provider lookup and the `tags: null` serialization
2. **Inject `BUILD_NUMBER`** in the Red Hat build pipeline so the health endpoint reports the actual version
3. **Update COMPATIBILITY.md** with current verified pairs — the only listed pair no longer exists as published artifacts
4. **Align the sidecar config schema** — either the operator should generate config for `0.3.0`'s schema, or the server should support both field paths
5. **Document the MLflow subpath requirement** — RHOAI MLflow serves under `/mlflow/`, and the sidecar proxy needs this in `tracking_uri` or all MLflow API calls return 500
