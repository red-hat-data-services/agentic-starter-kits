@AGENTS.md

# Claude-specific guidance

The `@AGENTS.md` include above provides structure, commands, code style, workflow,
boundaries, and non-standard agent details. The notes below cover things Claude Code
specifically needs that AGENTS.md does not address.

## Pre-commit hooks

This repo uses pre-commit hooks (defined in `.pre-commit-config.yaml`). They run
automatically on `git commit` and enforce:

- Conventional Commits format on commit messages
- Branch protection (`no-commit-to-branch`) -- blocks direct commits to `main`
- Python linting and formatting via `ruff`
- Markdown linting via `markdownlint`
- Link checking on markdown files via `lychee`
- Secret scanning via `gitleaks` (API keys, tokens, passwords -- broader than
  the private-key check)
- Lock file sync (`uv lock` on modified `pyproject.toml`)
- File-hygiene checks (trailing whitespace, end-of-file newline, YAML/JSON/TOML
  validation, merge conflict markers, large files, debug statements, private keys)

When a pre-commit hook modifies a file (e.g., ruff auto-fix, uv.lock update), the
commit will fail with "files were modified by this hook." Stage the modified files and
commit again.

## Dependency management

Every agent directory with a `pyproject.toml` must also have a committed `uv.lock`.
When modifying dependencies:

- Use lower-bound pins (`>=1.2.0`) in `pyproject.toml` -- avoid upper-bound caps
  unless a dependency has known breaking changes
- The `uv-lock` pre-commit hook auto-runs `uv lock` when `pyproject.toml` changes
- Always commit `uv.lock` alongside `pyproject.toml` changes

## Commit message format

This repo enforces Conventional Commits. PR titles become the commit message on `main`
(squash merge). Use the format:

```text
<type>(optional scope): <description>
```

Allowed types: `feat`, `fix`, `docs`, `chore`, `test`, `perf`, `refactor`, `ci`,
`build`, `style`, `revert`. Add `!` after type/scope for breaking changes.

## Linking PRs to Jira

Include a Jira ticket ID (e.g., `RHAIENG-123`) in the PR title, branch name, or
description so the PR automatically appears under Development on the Jira issue.

## Components directory

`components/` contains shared reusable packages consumed as dependencies by agents:

- `components/auth/` -- Python package for cross-agent authentication concerns
- `components/postgresql/` -- Helm chart for shared PostgreSQL infrastructure

These are consumed as package dependencies, not path imports. Never import directly
from a component's `src/` into an agent's `src/`.

## Additional non-standard agents

Beyond the non-standard agents listed in AGENTS.md, note these entries that follow
different patterns:

- `agents/claude-code/` -- Claude Code on OpenShift deployment guide. No `src/`,
  no `pyproject.toml`, no standard Makefile targets. Uses Containerfile with
  Anthropic's native installer. Do not redistribute built images (proprietary binary).
  See `agents/claude-code/README.md` for backend configurations (Anthropic API,
  Vertex AI, vLLM, OGX).
- `agents/opencode/` -- Deployment templates only, no standard agent structure.

## Claude Code skills

This project has a companion skills plugin
([agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills))
that automates common workflows. Key skills include:

- `integrate-tracing` -- end-to-end MLflow tracing integration for an agent
- `fit-check` -- validate whether a new agent belongs in the repo
- `add-behavioral-tests` / `run-behavioral-tests` -- scaffold and run behavioral tests
- `deploy-agents` -- deploy agents to OpenShift with auto-detected cluster config

Invoke skills with the `agentic-starter-kits-skills:` prefix (e.g.,
`/agentic-starter-kits-skills:integrate-tracing`). See CONTRIBUTING.md for the
full skill list and installation instructions.

## MLflow tracing

All agent templates must include MLflow tracing integration (opt-in via
`MLFLOW_TRACKING_URI`). When adding or modifying tracing:

- Tracing module goes in `src/<package>/tracing.py`
- Call `enable_tracing()` as the first line in the FastAPI `lifespan()` function
- MLflow is an optional dependency under the `tracing` extra in `pyproject.toml`
- See `tracing.md` at the repo root for the full architecture and autolog levels

## Workspace instructions for Claude Code deployments

When deploying Claude Code on OpenShift, `CLAUDE.md` can be mounted as a ConfigMap
to inject project-specific instructions into the session. Claude Code automatically
reads `CLAUDE.md` from the working directory. See
`agents/claude-code/README.md` for the mounting pattern.
