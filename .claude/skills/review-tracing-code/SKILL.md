---
name: review-tracing-code
description: Reviews tracing integration code for correctness against the repo's established patterns and checklists.
argument-hint: "<agent_path>"
disable-model-invocation: true
---

# Review Tracing Code

> **Usage:** `/review-tracing-code <agent_path>`
> **Example:** `/review-tracing-code agents/autogen/chat_agent`

You are reviewing the MLflow tracing integration code for an agent template to confirm it follows the repo's established patterns and is correctly wired.

**You must read every file and check every item yourself.** Do not ask the user to review files or run checks. Execute the full checklist and produce the report.

## Input

The agent path is: $ARGUMENTS

You also need the **package name** and **coverage level** (A, B, or C). If not provided, determine them by reading the agent's `pyproject.toml`, `src/` directory, and `tracing.py`.

## Review Checklist

### 1. `tracing.py` exists and follows the pattern

Read `<agent_path>/src/<package>/tracing.py` and verify:

- [ ] Logger setup is at module level with `logging.getLogger("tracing")`
- [ ] `check_mlflow_health()` is present and matches the reference (retry loop with time budget)
- [ ] `enable_tracing()` is present with the correct structure:
  - [ ] Calls `load_dotenv()` first
  - [ ] Returns early if `MLFLOW_TRACKING_URI` is not set
  - [ ] MLflow imports are lazy (inside the function, not at module top)
  - [ ] Health check with `MLFLOW_HEALTH_CHECK_TIMEOUT` support
  - [ ] Graceful degradation — returns without crashing if server is unreachable
  - [ ] Calls `mlflow.set_tracking_uri()`, `mlflow.set_experiment()`, `mlflow.config.enable_async_logging()` in that order
  - [ ] Calls the correct framework/provider autolog (see level-specific checks below)

**Level A**: Verify `mlflow.<framework>.autolog()` is called. No `wrap_func_with_mlflow_trace()` should exist.

**Level B**: Verify:
- [ ] Framework autolog is called (e.g., `mlflow.crewai.autolog()`)
- [ ] Provider-specific autolog is called (either hardcoded or via `LLM_PROVIDER` routing map)
- [ ] `wrap_func_with_mlflow_trace()` function exists with `span_type` and `name` parameters
- [ ] `wrap_func_with_mlflow_trace()` returns original function when `MLFLOW_TRACKING_URI` is not set

**Level C**: Verify:
- [ ] Provider autolog is called (e.g., `mlflow.openai.autolog()`)
- [ ] No framework autolog (since none exists)
- [ ] `wrap_func_with_mlflow_trace()` function exists
- [ ] `wrap_func_with_mlflow_trace()` returns original function when `MLFLOW_TRACKING_URI` is not set

Compare against the reference file for the matching level:
- Level A: `agents/langgraph/react_agent/src/react_agent/tracing.py`
- Level B: `agents/crewai/websearch_agent/src/crewai_web_search/tracing.py`
- Level C: `agents/vanilla_python/openai_responses_agent/src/openai_responses_agent/tracing.py`

### 2. `main.py` wiring

Read `<agent_path>/main.py` and verify:

- [ ] `enable_tracing` is imported from `<package>.tracing`
- [ ] `enable_tracing()` is called as the **first line** inside the `lifespan()` function (before agent initialization)
- [ ] For Level B/C: `wrap_func_with_mlflow_trace` is also imported

### 3. Manual wrapping (Level B and C only)

Skip this section for Level A.

**Tool wrapping** — find where tools are registered/created and verify:
- [ ] Every tool function/method is wrapped with `wrap_func_with_mlflow_trace(..., span_type="tool")`
- [ ] The `name` parameter is used when wrapping tool objects (so span names are meaningful)
- [ ] Wrapping happens before tools are passed to the agent

**Agent wrapping** — find the main agent entry point and verify:
- [ ] The agent's main function (e.g., `query()`, `run()`) is wrapped with `wrap_func_with_mlflow_trace(..., span_type="agent")`
- [ ] This creates a parent span that groups all tool and LLM calls under one trace

**Streaming path** — read `_handle_stream` in `main.py` and verify:
- [ ] If streaming creates a new agent instance (bypasses the adapter/closure), wrapping is duplicated in the streaming path
- [ ] Both tool wrapping and agent wrapping are applied in the streaming code
- [ ] If streaming uses the same agent instance as non-streaming, no duplication is needed

### 4. No direct MLflow imports in `main.py`

- [ ] `main.py` does NOT import `mlflow` directly — all MLflow interaction goes through `tracing.py`
- [ ] No `mlflow.trace()` calls appear in `main.py` — only `wrap_func_with_mlflow_trace()` from `tracing.py`

### 5. `.env.example` has MLflow variables

Read `<agent_path>/.env.example` and verify:

- [ ] **Local tracing section** exists with: `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`, `MLFLOW_HEALTH_CHECK_TIMEOUT`, `MLFLOW_HTTP_REQUEST_TIMEOUT`, `MLFLOW_HTTP_REQUEST_MAX_RETRIES`
- [ ] **OpenShift tracing section** exists with: `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_TOKEN`, `MLFLOW_EXPERIMENT_NAME`, `MLFLOW_TRACKING_INSECURE_TLS`, `MLFLOW_WORKSPACE`, `MLFLOW_TRACKING_AUTH`
- [ ] All variables are commented out (optional by default)

### 6. `README.md` has tracing documentation

Read `<agent_path>/README.md` and verify:

- [ ] A `### Tracing (optional)` section exists
- [ ] **Local MLflow config** — example env vars for local development
- [ ] **OpenShift MLflow config** — example env vars for OpenShift deployment with notes explaining each variable
- [ ] **MLflow server start** — `uv run --extra tracing mlflow server --port 5000` command is documented
- [ ] **Behavioral notes** — documents that tracing is optional, gracefully degrades if server is unreachable, and `MLFLOW_HEALTH_CHECK_TIMEOUT` controls wait time

### 7. `pyproject.toml` lists MLflow as optional

- [ ] `mlflow>=3.10.0` is in `[project.optional-dependencies]` under a `tracing` extra — NOT in core `dependencies`

### 8. `Makefile` auto-installs MLflow when tracing is enabled

- [ ] `run` target uses `$${MLFLOW_TRACKING_URI:+--extra tracing}` in the `uv run` command
- [ ] `run-cli` target (if it exists) uses the same flag

### 9. Dockerfile installs tracing extra (if Dockerfile exists)

- [ ] The package install step in `Dockerfile` includes the `tracing` extra (e.g., `".[tracing]"` instead of `"."`)

## Output

```text
## Code Review Report: <agent_name>

### tracing.py
- Exists: YES / NO
- Follows pattern: YES / NO
- Issues: <list or "None">

### main.py wiring
- enable_tracing() imported: YES / NO
- Called first in lifespan: YES / NO
- Issues: <list or "None">

### Manual wrapping (Level B/C only)
- Tools wrapped: YES / NO / N/A
- Agent entry point wrapped: YES / NO / N/A
- Streaming path covered: YES / NO / N/A
- Issues: <list or "None">

### .env.example
- Local tracing section: YES / NO
- OpenShift tracing section: YES / NO
- Issues: <list or "None">

### README.md
- Tracing (optional) section exists: YES / NO
- Local MLflow config: YES / NO
- OpenShift MLflow config: YES / NO
- MLflow server start step: YES / NO
- Behavioral notes: YES / NO
- Issues: <list or "None">

### pyproject.toml
- MLflow in optional tracing extra: YES / NO

### Makefile
- run target has --extra tracing flag: YES / NO
- run-cli target has --extra tracing flag: YES / NO / N/A

### Dockerfile
- Installs .[tracing] extra: YES / NO

### Overall: PASS / FAIL
```

If FAIL, specify which skill or step to re-run to fix the issues (e.g., "`create-tracing-module` — missing graceful degradation", "`integrate-tracing` Step 9 — .env.example missing OpenShift section", or "`integrate-tracing` Step 10 — README missing local MLflow install").

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
