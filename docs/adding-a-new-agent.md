# Adding a New Agent

This guide explains how to add a new agent template to this repository.

## 1. Choose the Right Location

Agents are organized by framework:

```text
agents/
  langgraph/
    templates/      # LangGraph agent templates
    examples/       # LangGraph business use-case demos
  llamaindex/
    templates/      # LlamaIndex agent templates
  vanilla_python/
    templates/      # Vanilla Python agents (no framework)
  langflow/
    templates/      # Langflow visual agents
  <new-framework>/
    templates/      # Add a new framework directory if needed
```

## 2. Copy an Existing Agent

Start from the closest existing agent:

```bash
cp -r agents/langgraph/templates/react_agent agents/<framework>/templates/<your_agent>
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
| `uv.lock` | Lock file for reproducible builds (run `uv lock` to generate) |
| `main.py` | FastAPI app with /chat/completions, /health endpoints |
| `README.md` | Setup, usage, and deployment instructions |
| `src/<agent_name>/` | Agent source code (agent.py, tools.py) |
| `tests/` | Tests directory |
| `examples/` | Example scripts |

### Flow-based agents (e.g., Langflow)

Some agents do not deploy a custom container. Instead, the "agent" is a flow definition (e.g., JSON) imported into a pre-existing platform instance. These agents should still have:

| File | Purpose |
|------|---------|
| `agent.yaml` | Same as above, but add `deploymentModel: flow-import` and adjust env vars to match the infrastructure stack |
| `Makefile` | Targets: `init`, `run`, `stop`, `clean`, `status`, `logs`, `help` |
| `.env.example` | Environment variables for the local infrastructure stack |
| `README.md` | Setup, usage, and deployment instructions |
| `flows/` | Flow definition files (JSON, YAML, etc.) |

These agents do **not** need: `Dockerfile`, `values.yaml`, `.dockerignore`, `pyproject.toml`, `main.py`, `src/`, `tests/`, `examples/`, `playground/`.

## 4. API Contract

All agents must expose these endpoints:

- `POST /chat/completions` — accepts `{"messages": [...], "stream": false}`, returns JSON response
- `POST /chat/completions` — accepts `{"messages": [...], "stream": true}`, returns SSE stream with `Content-Type: text/event-stream` and no-cache / no-buffering headers
- `GET /health` — returns `{"status": "healthy", "agent_initialized": true}`

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
cd agents/<framework>/templates/<your_agent>
make init && make run                # local test
make dry-run                         # preview Helm manifests
make build && make push && make deploy  # OpenShift test (via registry)
make build-openshift && make deploy    # OpenShift test (in-cluster build)
```

## 10. Register the Lock File Hook

Add a `uv-lock` entry for your agent in `.pre-commit-config.yaml` under the `astral-sh/uv-pre-commit` repo:

```yaml
      - id: uv-lock
        name: uv-lock (<framework>/<your_agent>)
        files: ^agents/<framework>/templates/<your_agent>/pyproject\.toml$
        args: [--project, agents/<framework>/templates/<your_agent>]
```

This ensures the lock file is auto-updated whenever `pyproject.toml` changes. See [CONTRIBUTING.md](../CONTRIBUTING.md#dependency-management) for details.

## 11. Update Root README

Add your agent to the agent table in the root `README.md`.
