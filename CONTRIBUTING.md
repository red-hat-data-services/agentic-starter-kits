# Contributing to Agentic starter kits

Thank you for your interest in contributing. This document gives a short overview of how to get involved.

## How to contribute

- **Report bugs or suggest features** – Open an [issue](https://github.com/red-hat-data-services/agentic-starter-kits/issues) and describe the problem or idea. Check existing issues first to avoid duplicates.

- **Submit code changes** – Create a branch (in your fork or directly in this repo if you have access), make your changes, and open a pull request (PR). You don’t need to fork if you can push branches here. Keep PRs focused; one feature or fix per PR is easier to review.

- **Improve documentation** – Fixes and clarifications in the README, agent docs, or code comments are always welcome. Use the `docs:` prefix in your commit (see below).

- **Add or fix tests** – If you add or change behavior, consider adding or updating tests and use the `test:` prefix in commits.

Before submitting, please read our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Commit message conventions

We encourage [Conventional Commits](https://www.conventionalcommits.org/) so that history and release notes stay clear.

Use one of these prefixes at the start of your commit message:

| Prefix    | Meaning |
| --------- | -------- |
| **feat:** | A new feature |
| **fix:**  | A bug fix |
| **perf:** | A change that improves performance |
| **chore:**| Maintenance (deps, tooling, config) |
| **docs:** | Documentation only |
| **test:** | Adding or updating tests |

You can optionally add a scope (e.g. the agent or module name) in parentheses after the type.

### Examples

```
feat: add health check endpoint to autogen mcp_agent
fix: correct env var name in deployment in langgraph_react_agent
docs: update README with OpenShift deploy steps
test: add tests for tool registration
chore: bump python-dotenv in requirements
```

This is optional but appreciated; maintainers may ask you to reword commits when preparing a release.

## Adding MLflow tracing to your agent template

All agent templates in this repo must include MLflow tracing integration. Tracing lets users optionally capture LLM calls, tool executions, and agent orchestration spans in MLflow — it's opt-in via the `MLFLOW_TRACKING_URI` environment variable. If `MLFLOW_TRACKING_URI` is set but the server is unreachable, the agent logs a warning and continues without tracing. Note: if `MLFLOW_TRACKING_URI` is set but the MLflow package is not installed, the agent will fail at startup with an `ImportError` — MLflow must be installed when the env var is set.

Read [tracing.md](tracing.md) for the full tracing architecture, design principles, and how the existing agents integrate with MLflow. In particular, see the [Autolog Coverage Levels](tracing.md#autolog-coverage-levels) section — the amount of work required depends on whether your framework is Level A (full autolog), B (partial), or C (no framework autolog).

### What you need to do

These are the files you need to create or update when adding tracing to your agent:

**1. Create `src/<package>/tracing.py`**

This module exports `enable_tracing()` (and `wrap_func_with_mlflow_trace()` if your framework's autolog doesn't cover everything). It handles health-checking the MLflow server with retry logic, configuring the experiment, enabling the correct autolog for your framework, and gracefully degrading if the server is unreachable. MLflow imports are inside `enable_tracing()` (not at module top) so the module can be imported without MLflow installed — but if `MLFLOW_TRACKING_URI` is set and MLflow is missing, the agent will fail at startup with a clear error.

See existing examples:
- Full autolog (no manual wrapping needed): `agents/langgraph/react_agent/src/react_agent/tracing.py`
- Partial autolog (tools need manual wrapping): `agents/crewai/websearch_agent/src/crewai_web_search/tracing.py`
- No framework autolog (tools + agent entry point need manual wrapping): `agents/vanilla_python/openai_responses_agent/src/openai_responses_agent/tracing.py`

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

If you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code) set up, this repo includes a skill that automates the entire process described above.

#### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- Run Claude Code from the repo root so it discovers the skills in `.claude/skills/`

#### Running the full integration

```text
/integrate-tracing <framework> <agent_path>
```

For example:

```text
/integrate-tracing autogen agents/autogen/chat_agent
```

You can also prompt Claude Code directly (e.g., "integrate tracing into the autogen chat agent using the `/integrate-tracing` skill") and it will follow the same workflow.

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
/check-autolog-support <framework>         # Research MLflow autolog support for a framework
/create-tracing-module <agent_path> [framework]  # Create tracing.py only
/wire-into-lifespan <agent_path>            # Wire tracing into main.py only
/add-manual-tracing <agent_path>            # Add manual trace wrapping only
/verify-traces <agent_path>                 # Run code review + live trace testing
/review-tracing-code <agent_path>           # Code review only (no live testing)
/test-tracing <agent_path>                  # Live trace testing only (no code review)
```

#### How the skill system works

`integrate-tracing` is an orchestrator — it doesn't contain all the logic itself. Instead, it coordinates 7 specialized sub-skills in sequence, passing context between them. The most important piece of context is the **autolog level** (A, B, or C), which is determined in Step 1 by `check-autolog-support` and drives every decision downstream: what code `create-tracing-module` generates, what `wire-into-lifespan` imports, whether `add-manual-tracing` runs at all, and what spans `verify-traces` expects to find.

`verify-traces` is itself a sub-orchestrator — it calls `review-tracing-code` (static analysis) and `test-tracing` (live end-to-end testing) and combines their results into a single report. If verification fails, the report points back to which step to revisit.

All skills live as siblings in `.claude/skills/` (not nested under `integrate-tracing/`) because Claude Code discovers skills by scanning `.claude/skills/*/SKILL.md`. The flat structure also makes each sub-skill independently callable. If you need to maintain or extend a skill, edit the `SKILL.md` file in its directory. Each skill includes a self-update instruction — if Claude deviates from a skill's steps because they were inaccurate, it updates the skill file automatically so the next run benefits.

**Recommended model:** These skills were developed and tested with `claude-opus-4-6`. Use Opus for best results — smaller models may not follow the multi-step orchestration reliably.

## Questions?

See the main [README](README.md) or open an issue. You can also contact [wrebisz@redhat.com](mailto:wrebisz@redhat.com) or [tguzik@redhat.com](mailto:tguzik@redhat.com).
