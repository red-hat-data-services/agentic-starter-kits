# Adding a New Agent

This guide explains how to add a new agent template to this repository.

## 1. Choose the Right Location

Agents are organized by framework:

```
agents/
  langgraph/        # LangGraph-based agents
  llamaindex/       # LlamaIndex-based agents
  vanilla_python/   # Vanilla Python agents (no framework)
  langflow/         # Langflow visual agents
  <new-framework>/  # Add a new framework directory if needed
```

## 2. Copy an Existing Agent

Start from the closest existing agent:

```bash
cp -r agents/langgraph/react_agent agents/<framework>/<your_agent>
```

## 3. Required Files

Every agent must have:

| File | Purpose |
|------|---------|
| `agent.yaml` | Metadata: name, framework, description, required env vars |
| `values.yaml` | Helm values override (nameOverride, env vars, resources) |
| `.env.example` | Template for local environment variables |
| `Makefile` | Consistent interface: init, run, build, build-openshift, deploy, dry-run, test |
| `Dockerfile` | Container build (UBI9 Python 3.12, non-root user, port 8080) |
| `pyproject.toml` | Python dependencies |
| `main.py` | FastAPI app with /chat/completions, /health endpoints |
| `README.md` | Setup, usage, and deployment instructions |
| `src/<agent_name>/` | Agent source code (agent.py, tools.py) |
| `tests/` | Tests directory |
| `examples/` | Example scripts |

## 4. API Contract

All agents must expose these endpoints:

- `POST /chat/completions` — accepts `{"messages": [...], "stream": false}`, returns response
- `POST /chat/completions` — accepts `{"messages": [...], "stream": true}`, returns SSE stream
- `GET /health` — returns `{"status": "healthy"}`

## 5. Update agent.yaml

```yaml
name: <framework>-<agent-name>       # used as Helm release name
displayName: "Human-Readable Name"
framework: <framework>
description: "One-line description"
env:
  required:
    - API_KEY
    - BASE_URL
    - MODEL_ID
  optional:
    - PORT
    - CONTAINER_IMAGE
```

## 6. Update values.yaml

Set `nameOverride` to match `agent.yaml`'s `name` field. Add any agent-specific env vars, resource overrides, or volumes.

## 7. Update Makefile

If your agent has extra env vars, add them as `--set` flags in the `deploy` and `dry-run` targets.

The Makefile auto-detects Podman or Docker (preferring Podman) via:

```makefile
CONTAINER_CLI := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
```

Every Makefile includes a `build-openshift` target for in-cluster builds (no Podman/Docker needed).

## 8. Dockerfile Conventions

- Base image: `registry.access.redhat.com/ubi9/python-312:latest` (avoids Docker Hub rate limits on OpenShift)
- Non-root user: UID 1001 (UBI9 default) with GID 0 for OpenShift arbitrary UID support
- Port: 8080
- Use `uv pip install` for dependencies
- Set `PYTHONPATH=/opt/app-root/src`

## 9. Test Your Agent

```bash
cd agents/<framework>/<your_agent>
make init && make run                # local test
make dry-run                         # preview Helm manifests
make build && make push && make deploy  # OpenShift test (via registry)
make build-openshift && make deploy    # OpenShift test (in-cluster build)
```

## 10. Update Root README

Add your agent to the agent table in the root `README.md`.
