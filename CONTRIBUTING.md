# Contributing to Agentic starter kits

Thank you for your interest in contributing. This document gives a short overview of how to get involved.

## How to contribute

- **Report bugs or suggest features** – Open an [issue](https://github.com/red-hat-data-services/agentic-starter-kits/issues) and describe the problem or idea. Check existing issues first to avoid duplicates.

- **Submit code changes** – Create a branch (in your fork or directly in this repo if you have access), make your changes, and open a pull request (PR). You don’t need to fork if you can push branches here. Keep PRs focused; one feature or fix per PR is easier to review. When creating a PR, use the [PR template](.github/PULL_REQUEST_TEMPLATE.md) and fill in each section.

- **Improve documentation** – Fixes and clarifications in the README, agent docs, or code comments are always welcome. Use the `docs:` prefix in your commit (see below).

- **Add or fix tests** – If you add or change behavior, consider adding or updating tests and use the `test:` prefix in commits.

Before submitting, please read our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Proposing a new agent

Before writing code for a new agent template or example, validate that it belongs in this repository. Every agent in this repo should complete the sentence:

> "As an AI engineer, I need to know how to build an agent using **\_\_\_\_\_** and integrate it with these RHOAI components: **\_\_\_\_\_** for **\_\_\_\_\_**"

### Step 1: Run the fit check

The recommended path is to validate your idea **before writing any code**. Run the fit-check skill or answer the manual questionnaire, then post the result as a GitHub Discussion. Wait for maintainer approval before proceeding to implementation.

**Using the fit-check skill (recommended):**

If you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and the [agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills) plugin installed:

```text
/agentic-starter-kits-skills:fit-check
```

The skill asks a series of questions and generates a GitHub Discussion draft with a fit score (**GREEN** / **YELLOW** / **RED**) and recommendations.

**Manual fit check (no Claude Code):**

Answer these questions and post them as a [GitHub Discussion](https://github.com/red-hat-data-services/agentic-starter-kits/discussions):

1. **Framework**: Which agent framework? (See `agents/` for existing frameworks, or name a new one)
2. **Type**: Template (reusable, general-purpose) or example (business use-case demo)?
3. **RHOAI components**: Which platform components does it integrate with? (OGX/vLLM for inference, MLflow for tracing, Milvus for vector search, PostgreSQL for memory, MCP servers for tools)
4. **Differentiation**: What does this agent teach that the existing agents don't?
5. **API contract**: Will it expose `POST /chat/completions` (JSON + SSE streaming) and `GET /health`?
6. **Container pattern**: Will it use UBI9, port 8080, non-root UID 1001?

### Step 2: Wait for approval, then implement

| Score | Meaning | Action |
|-------|---------|--------|
| **GREEN** | Sentence completes, standard components, no overlap, standard conformance | Proceed to implementation |
| **YELLOW** | Sentence completes but has flags (non-standard components, partial overlap, new framework) | Wait for maintainer + PM feedback in the Discussion before writing code |
| **RED** | Can't complete the sentence (deployment-only, no RHOAI integration) or exact duplicate | Needs rethinking or PM decision on scope |

Link the approved Discussion in your PR description when you submit code.

### Already opened a PR without a fit check?

This is a fallback for PRs already in flight. Run the fit check against your agent directory — the skill auto-extracts details from your code:

```text
/agentic-starter-kits-skills:fit-check langgraph/templates/my_agent
```

Post the generated Discussion and add the link to your PR. Review is paused until the proposal Discussion is approved.

## Development setup

This repository uses [pre-commit](https://pre-commit.com/) hooks to enforce code quality checks before each commit. Set it up once after cloning:

```bash
uv tool install pre-commit
pre-commit install --install-hooks
```

After this, every `git commit` will automatically run the checks listed in [Pre-commit hooks](#pre-commit-hooks) on your staged files. Commits that fail any check will be blocked.

If you haven't run `pre-commit install --install-hooks`, hooks will **not** run automatically. In that case, you can run all checks manually before committing:

```bash
pre-commit run --all-files
```

## Dependency management

Every agent directory that has a `pyproject.toml` must also contain a committed `uv.lock` file so that builds are fully reproducible. When adding a new agent or modifying dependencies:

1. **Use lower-bound pins** (e.g. `>=1.2.0`) in `pyproject.toml` to express minimum required versions. Avoid upper-bound caps in most cases — the lock file handles reproducibility. Upper bounds may be necessary when a dependency has known breaking changes or framework-imposed compatibility constraints.
2. **Lock files are auto-updated** — the `uv-lock` pre-commit hook runs `uv lock` automatically when you modify a `pyproject.toml`. If the lock file changes, the hook will update it and fail the commit; simply re-commit to include the updated lock file.
3. **Commit `uv.lock`** alongside `pyproject.toml` changes — never `.gitignore` it.
4. CI enforces lock file consistency via `uv lock --check` in the Code Quality workflow.

## Pre-commit hooks

The following hooks run automatically on every commit. They are defined in [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

### Conventional commits

Enforces the [Conventional Commits](https://www.conventionalcommits.org/) format on commit messages (see [Commit message conventions](#commit-message-conventions) below). Runs at the `commit-msg` stage.

### Python linting and formatting (ruff)

Two hooks from [ruff](https://docs.astral.sh/ruff/):

- **ruff** — lints Python files and auto-fixes issues. Rules are defined in [`ruff.toml`](ruff.toml).
- **ruff-format** — enforces consistent formatting (quotes, indentation, line length).

### Markdown linting (markdownlint)

Lints `.md` files and auto-fixes what it can (e.g., list indentation, code block languages). Rules are defined in [`.markdownlint.jsonc`](.markdownlint.jsonc); ignored paths in [`.markdownlint-cli2.yaml`](.markdownlint-cli2.yaml).

### File-hygiene hooks

General-purpose checks from [pre-commit/pre-commit-hooks](https://github.com/pre-commit/pre-commit-hooks):

| Hook | What it does |
| ---- | ------------ |
| `trailing-whitespace` | Removes trailing whitespace from all files |
| `end-of-file-fixer` | Ensures every file ends with a newline |
| `check-yaml` | Validates YAML syntax (excludes `agents/*/deployment/` — Helm templates use Go syntax) |
| `check-json` | Validates JSON syntax |
| `check-toml` | Validates TOML syntax |
| `check-merge-conflict` | Detects leftover merge conflict markers |
| `check-added-large-files` | Blocks files larger than 1 MB |
| `debug-statements` | Catches leftover `breakpoint()` / `pdb` calls in Python |
| `check-case-conflict` | Detects filenames that differ only in case |
| `mixed-line-ending` | Ensures consistent line endings (no mixed LF/CRLF) |
| `no-commit-to-branch` | Blocks direct commits to `main` |
| `detect-private-key` | Catches accidentally committed private keys |

### Lock file sync (uv-lock)

Runs `uv lock` on any modified `pyproject.toml` and auto-updates the corresponding `uv.lock` if it's stale. The commit will fail with "files were modified by this hook" — simply re-commit to include the updated lock file.

### GitHub Actions workflow validation (actionlint)

Validates `.github/workflows/` files using [actionlint](https://github.com/rhysd/actionlint). Only runs when workflow files are staged.

## Linting and formatting

This project uses [ruff](https://docs.astral.sh/ruff/) for Python linting and formatting, [markdownlint](https://github.com/DavidAnson/markdownlint) for Markdown linting, and [actionlint](https://github.com/rhysd/actionlint) for GitHub Actions workflow validation. All three run as blocking CI checks on every pull request via the `Code Quality` workflow, and locally via the [pre-commit hooks](#pre-commit-hooks) described above.

Configuration files: [`ruff.toml`](ruff.toml) (Python rules), [`.markdownlint.jsonc`](.markdownlint.jsonc) (Markdown rules), [`.markdownlint-cli2.yaml`](.markdownlint-cli2.yaml) (ignored paths).

## Commit message conventions

This repository enforces the [Conventional Commits](https://www.conventionalcommits.org/) specification via a pre-commit hook. Commits that don't follow this format will be blocked locally by the pre-commit hook. All PRs are squash-merged, so the **PR title** becomes the commit message on `main` — make sure it follows Conventional Commits format.

> **Tip:** To bypass the hook in rare cases (e.g., merge commits, emergency hotfixes): `git commit --no-verify`

### Format

```text
<type>(optional scope): <description>

[optional body]

[optional footer(s)]
```

### Allowed types

| Prefix        | Meaning |
| ------------- | -------- |
| **feat:**     | A new feature |
| **fix:**      | A bug fix |
| **docs:**     | Documentation only |
| **chore:**    | Maintenance (deps, tooling, config) |
| **test:**     | Adding or updating tests |
| **perf:**     | A change that improves performance |
| **refactor:** | Code change that neither fixes a bug nor adds a feature |
| **ci:**       | CI/CD changes |
| **build:**    | Build system or external dependency changes |
| **style:**    | Code style (formatting, whitespace — no logic changes) |
| **revert:**   | Reverts a previous commit |

You can optionally add a scope (e.g. the agent or module name) in parentheses after the type.

### Examples

```text
feat: add health check endpoint to autogen mcp_agent
fix: correct env var name in deployment in langgraph_react_agent
docs: update README with OpenShift deploy steps
test: add tests for tool registration
chore: bump python-dotenv in requirements
refactor(langgraph): extract tool registration into helper
ci: add ruff linting workflow
feat!: change /chat response format
```

For breaking changes, add `!` after the type/scope (e.g. `feat!:`) or include a `BREAKING CHANGE:` footer:

```text
feat: change /chat response format

BREAKING CHANGE: response field "text" renamed to "content"
```

## Linking PRs to Jira

This repository has GitHub + Jira integration enabled. When you include a Jira ticket ID (e.g. `RHAIENG-123`) in your PR title, branch name, commit message, or PR description, the pull request automatically appears under **Development** on the Jira issue. This gives visibility into which tickets have active or merged code without leaving Jira.

## Automated PR labels

Every pull request is automatically labeled when opened or updated:

**Area labels** (`area/*`) — applied based on which directories your PR touches. A PR can have multiple area labels if it spans several directories. These help reviewers quickly identify which parts of the codebase are affected.

| Label | Matches |
|-------|---------|
| `area/langgraph` | `agents/langgraph/**` |
| `area/crewai` | `agents/crewai/**` |
| `area/autogen` | `agents/autogen/**` |
| `area/llamaindex` | `agents/llamaindex/**` |
| `area/langflow` | `agents/langflow/**` |
| `area/google-adk` | `agents/google/**` |
| `area/a2a` | `agents/a2a/**` |
| `area/vanilla-python` | `agents/vanilla_python/**` |
| `area/helm` | `agents/*/deployment/**` |
| `area/docs` | `docs/**`, `*.md` (root) |
| `area/ci` | `.github/**` |
| `area/tests` | `tests/**`, `eval/**` |
| `area/tracing` | `**/tracing.py`, `tracing.md` |

**Size labels** (`size/*`) — applied based on total lines changed (additions + deletions), excluding lock files, generated files, and images.

| Label | Lines Changed |
|-------|--------------|
| `size/xs` | 0–10 |
| `size/s` | 11–100 |
| `size/m` | 101–500 |
| `size/l` | 501–1199 |
| `size/xl` | 1200+ |

PRs labeled `size/xl` will receive an advisory comment encouraging the author to consider splitting the PR. This is informational only — it does not block merges.

## Adding MLflow tracing to your agent template

All agent templates in this repo must include MLflow tracing integration. Tracing lets users optionally capture LLM calls, tool executions, and agent orchestration spans in MLflow — it's opt-in via the `MLFLOW_TRACKING_URI` environment variable. If `MLFLOW_TRACKING_URI` is set but the server is unreachable, the agent logs a warning and continues without tracing. Note: if `MLFLOW_TRACKING_URI` is set but the MLflow package is not installed, the agent will fail at startup with an `ImportError` — MLflow must be installed when the env var is set.

Read [tracing.md](tracing.md) for the full tracing architecture, design principles, and how the existing agents integrate with MLflow. In particular, see the [Autolog Coverage Levels](tracing.md#autolog-coverage-levels) section — the amount of work required depends on whether your framework is Level A (full autolog), B (partial), or C (no framework autolog).

### What you need to do

These are the files you need to create or update when adding tracing to your agent:

**1. Create `src/<package>/tracing.py`**

This module exports `enable_tracing()` (and `wrap_func_with_mlflow_trace()` if your framework's autolog doesn't cover everything). It handles health-checking the MLflow server with retry logic, configuring the experiment, enabling the correct autolog for your framework, and gracefully degrading if the server is unreachable. MLflow imports are inside `enable_tracing()` (not at module top) so the module can be imported without MLflow installed — but if `MLFLOW_TRACKING_URI` is set and MLflow is missing, the agent will fail at startup with a clear error.

See existing examples:

- Full autolog (no manual wrapping needed): `agents/langgraph/templates/react_agent/src/react_agent/tracing.py`
- Partial autolog (tools need manual wrapping): `agents/crewai/templates/websearch_agent/src/crewai_web_search/tracing.py`
- No framework autolog (tools + agent entry point need manual wrapping): `agents/vanilla_python/templates/openai_responses_agent/src/openai_responses_agent/tracing.py`

**2. Edit `main.py`**

Import `enable_tracing` and call it as the **first line** inside your `lifespan()` function, before any agent initialization. If your framework needs manual wrapping, also import `wrap_func_with_mlflow_trace` and wrap tool functions (`span_type="tool"`) and the agent entry point (`span_type="agent"`) — in both the streaming and non-streaming code paths.

**3. Edit `.env.example`**

Add commented-out MLflow environment variable sections for both local and OpenShift deployment (see any existing agent's `.env.example` for the format).

**4. Edit `README.md`**

Add tracing configuration examples (local and OpenShift) and the `uv run --extra tracing mlflow server --port 5000` server start step.

**5. Add MLflow as an optional dependency in `pyproject.toml`**

MLflow is listed as an optional dependency under the `tracing` extra:

```toml
[project.optional-dependencies]
tracing = [
    "mlflow>=3.10.0",
]
```

This allows `make run` to auto-install MLflow when `MLFLOW_TRACKING_URI` is set (via `uv run --extra tracing`). MLflow is not a core dependency — agents run without it when tracing is disabled.

### Using the `integrate-tracing` Claude Code skill

If you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code) set up, the [agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills) plugin includes a skill that automates the entire process described above.

#### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- Install the [agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills) plugin (see [Claude Code skills](#claude-code-skills))

#### Running the full integration

```text
/agentic-starter-kits-skills:integrate-tracing <framework> <agent_path>
```

For example:

```text
/agentic-starter-kits-skills:integrate-tracing autogen agents/autogen/templates/mcp_agent
```

You can also prompt Claude Code directly (e.g., "integrate tracing into the autogen MCP agent using the `/agentic-starter-kits-skills:integrate-tracing` skill") and it will follow the same workflow.

This single command runs the entire pipeline end-to-end. The skill always creates a demo copy of the agent first, implements and verifies tracing on the demo, and only applies the changes to the actual agent template once everything works correctly.

1. Researches your framework's MLflow autolog support and classifies it (Level A/B/C)
2. Creates a demo copy of the agent with test tools for trace verification
3. Reads the agent's code to understand its architecture
4. Creates `tracing.py` with the correct pattern for the autolog level
5. Wires `enable_tracing()` into the FastAPI lifespan in `main.py`
6. Adds manual trace wrapping for tools and agent entry points (skipped if autolog covers everything)
7. Verifies traces end-to-end — code review + live testing against the MLflow API
8. Updates `.env.example` with MLflow environment variables
9. Updates `README.md` with tracing configuration and install steps

#### Running individual sub-skills

Each step of the pipeline is also available as a standalone skill. This is useful if you want to run just one phase, re-run a step after a fix, or integrate tracing manually with some automation:

```text
/agentic-starter-kits-skills:check-autolog-support <framework>         # Research MLflow autolog support for a framework
/agentic-starter-kits-skills:create-tracing-module <agent_path> [framework]  # Create tracing.py only
/agentic-starter-kits-skills:wire-into-lifespan <agent_path>            # Wire tracing into main.py only
/agentic-starter-kits-skills:add-manual-tracing <agent_path>            # Add manual trace wrapping only
/agentic-starter-kits-skills:verify-traces <agent_path>                 # Run code review + live trace testing
/agentic-starter-kits-skills:review-tracing-code <agent_path>           # Code review only (no live testing)
/agentic-starter-kits-skills:test-tracing <agent_path>                  # Live trace testing only (no code review)
```

#### How the skill system works

`integrate-tracing` is an orchestrator — it doesn't contain all the logic itself. Instead, it coordinates 7 specialized sub-skills in sequence, passing context between them. The most important piece of context is the **autolog level** (A, B, or C), which is determined in Step 1 by `check-autolog-support` and drives every decision downstream: what code `create-tracing-module` generates, what `wire-into-lifespan` imports, whether `add-manual-tracing` runs at all, and what spans `verify-traces` expects to find.

`verify-traces` is itself a sub-orchestrator — it calls `review-tracing-code` (static analysis) and `test-tracing` (live end-to-end testing) and combines their results into a single report. If verification fails, the report points back to which step to revisit.

All contributor and operator skills live in the [agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills) plugin repo as a flat set of siblings. The flat structure makes each sub-skill independently callable. If you need to maintain or extend a skill, edit the `SKILL.md` file in its directory in the plugin repo. Each skill includes a self-update instruction — if Claude deviates from a skill's steps because they were inaccurate, it updates the skill file automatically so the next run benefits. See [Claude Code skills](#claude-code-skills) for the full skill list.

**Recommended model:** These skills were developed and tested with `claude-opus-4-6`. Use Opus for best results — smaller models may not follow the multi-step orchestration reliably.

## Claude Code skills

This project uses [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills to automate common contributor workflows. All contributor and operator skills live in the [agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills) plugin repo.

### Available skills

| Skill | Description |
|-------|-------------|
| `integrate-tracing` | End-to-end MLflow tracing integration (see [Adding MLflow tracing](#adding-mlflow-tracing-to-your-agent-template)) |
| `check-autolog-support` | Research MLflow autolog support for a framework |
| `create-tracing-module` | Create `tracing.py` for an agent |
| `wire-into-lifespan` | Wire tracing into the FastAPI lifespan |
| `add-manual-tracing` | Add manual trace wrapping for tools and agent entry points |
| `verify-traces` | Code review + live trace testing |
| `review-tracing-code` | Static code review of tracing implementation |
| `test-tracing` | Live end-to-end trace testing |
| `kagenti-deploy` | Deploy A2A-compliant agents to OpenShift with kagenti integration |
| `deploy-agents` | Deploy agents to OpenShift with auto-detected cluster config and MLflow token refresh |
| `fit-check` | Validate whether a new agent belongs in the repo (idea mode or existing code) |
| `add-behavioral-tests` | Scaffold behavioral testing (pytest + EvalHub) for an agent |
| `run-behavioral-tests` | Run and validate behavioral tests for an agent |
| `add-integration-tests` | Add integration tests for agent deployment verification |

### Installation

```bash
claude plugin marketplace add red-hat-data-services/agentic-starter-kits-skills
claude plugin install agentic-starter-kits-skills@agentic-starter-kits-skills
```

After installing, invoke skills with the `agentic-starter-kits-skills:` prefix (e.g. `/agentic-starter-kits-skills:deploy-agents`).

### Adding a new skill

Contributor and operator skills (test scaffolding, deployment, tracing integration, code generation) go in the [plugin repo](https://github.com/red-hat-data-services/agentic-starter-kits-skills). See its [Contributing section](https://github.com/red-hat-data-services/agentic-starter-kits-skills#contributing) for how to add one.

End-user-facing skills — ones that help someone who cloned a starter kit customize or run an agent for their own use case — can go in this repo under `.claude/skills/` so they're available without installing the plugin. Create the directory when adding the first skill.

## Questions?

See the main [README](README.md) or open an issue. You can also contact [wrebisz@redhat.com](mailto:wrebisz@redhat.com) or [tguzik@redhat.com](mailto:tguzik@redhat.com).
