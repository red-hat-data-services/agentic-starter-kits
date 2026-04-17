---
name: create-tracing-module
description: Creates the tracing.py module with enable_tracing(), health check, and framework-specific autolog configuration.
argument-hint: "<agent_path> [framework]"
disable-model-invocation: true
---

# Create the Tracing Module (`tracing.py`)

> **Usage:** `/create-tracing-module <agent_path>`
> **Example:** `/create-tracing-module agents/autogen/chat_agent`

You are creating the `tracing.py` file for a new agent template, following this repo's established patterns.

## Input

The agent path is: $ARGUMENTS

You also need the **framework name** (e.g., `autogen`, `langgraph`, `crewai`) and the **autolog support report** (which classifies the framework as Level A, B, or C). The framework may be included as a second word in `$ARGUMENTS`. If not provided, determine it from the agent's `pyproject.toml` dependencies.

If the autolog report is not available in the current conversation context, read and follow check-autolog-support skill from `.claude/skills/check-autolog-support/SKILL.md` with the framework name to produce the report before continuing.

## Context

Read `tracing.md` at the repo root for the full tracing architecture, design principles, and how each existing agent integrates with MLflow.

## Reference Files

Read the reference `tracing.py` that matches the coverage level. These are the source of truth — follow their patterns exactly:

- **Level A — autolog variant** (full autolog): `agents/langgraph/react_agent/src/react_agent/tracing.py`
- **Level A — OTel variant** (framework emits OTel spans): `agents/google/adk/src/adk_agent/tracing.py`
- **Level B** (partial autolog): `agents/crewai/websearch_agent/src/crewai_web_search/tracing.py`
- **Level C** (no framework autolog): `agents/vanilla_python/openai_responses_agent/src/openai_responses_agent/tracing.py`

## What to Create

Create the file at: `<agent_path>/src/<package_name>/tracing.py`

The `<package_name>` is the Python package name — find it by looking at the existing `src/` directory or `pyproject.toml` `[tool.setuptools.packages.find]`.

## How to Build It

### Shared code (all levels)

Copy these **exactly** from the reference file — they are identical across all agents:
- Logger setup (module-level `logging.getLogger("tracing")` with handler)
- `check_mlflow_health()` function (retry loop with time budget)
- `enable_tracing()` skeleton (load_dotenv, MLFLOW_TRACKING_URI check, health check with graceful degradation, set_tracking_uri, set_experiment, enable_async_logging)

### Framework-specific code

The **only parts that differ** between levels are inside `enable_tracing()` and whether `wrap_func_with_mlflow_trace()` exists:

**Level A (autolog variant)** — Read the LangGraph reference. Adapt by:
- Replacing the `import mlflow.langchain` / `mlflow.langchain.autolog()` with the correct module for the new framework (from the autolog report)
- No `wrap_func_with_mlflow_trace()` needed

**Level A (OTel variant)** — Read the Google ADK reference. Use this when the framework has no `mlflow.<framework>.autolog()` but natively emits OpenTelemetry spans. Adapt by:
- Setting up `TracerProvider` with `OTLPSpanExporter` pointing at `{tracking_uri}/v1/traces`
- Passing the experiment ID via the `x-mlflow-experiment-id` header (get it from `mlflow.set_experiment()`)
- The MLflow server requires a SQL backend (`--backend-store-uri sqlite:///mlflow.db`)
- Extra package: `opentelemetry-exporter-otlp-proto-http`
- No `wrap_func_with_mlflow_trace()` needed

**Level B** — Read the CrewAI reference. Adapt by:
- Replacing the framework autolog module (e.g., `mlflow.crewai` → `mlflow.<new_framework>`)
- Adjusting the provider autolog routing if the new framework's LLM provider path differs. If the framework uses a single LLM path, simplify by hardcoding the provider autolog instead of the `provider_autolog_map` + `LLM_PROVIDER` routing
- Copying `wrap_func_with_mlflow_trace()` as-is (with `name` parameter)

**Level C** — Read the Vanilla Python reference. Adapt by:
- Replacing the provider autolog module if the framework uses a different LLM SDK (from the autolog report)
- Copying `wrap_func_with_mlflow_trace()` as-is

## Final Checklist

After creating the file, verify:
- [ ] Logger setup is at module level (not inside a function)
- [ ] `check_mlflow_health()` is identical to the reference
- [ ] `enable_tracing()` has graceful degradation (returns on unreachable server, doesn't crash)
- [ ] MLflow imports are lazy (inside `enable_tracing()` / `wrap_func_with_mlflow_trace()`, not at module top)
- [ ] `wrap_func_with_mlflow_trace()` returns the original function unchanged when `MLFLOW_TRACKING_URI` is not set
- [ ] The correct autolog module is used for the framework
- [ ] `enable_async_logging()` is called before autolog

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
