---
name: wire-into-lifespan
description: Wires enable_tracing() into the FastAPI lifespan and adds manual trace wrapping imports to main.py.
argument-hint: "<agent_path>"
disable-model-invocation: true
---

# Wire Tracing into the FastAPI Lifespan

> **Usage:** `/wire-into-lifespan <agent_path>`
> **Example:** `/wire-into-lifespan agents/autogen/chat_agent`

You are connecting the `tracing.py` module to the agent's FastAPI app so that tracing is initialized at startup.

## Input

The agent path is: $ARGUMENTS

You also need the **package name** and **coverage level** (A, B, or C). If not provided, determine them by reading the agent's `pyproject.toml` and `src/` directory.

## Steps

### 1. Read the agent's `main.py`

Read `<agent_path>/main.py` to understand:
- The existing `lifespan()` function
- How the agent is initialized (what global variables, closures, etc.)
- Whether there's a streaming path that creates the agent differently from non-streaming

### 2. Add the tracing import

Add the import at the top of `main.py`, near the other package imports:

**Level A (full autolog):**
```python
from <package_name>.tracing import enable_tracing
```

**Level B or C (needs manual wrapping):**
```python
from <package_name>.tracing import enable_tracing, wrap_func_with_mlflow_trace
```

### 3. Add `enable_tracing()` to the lifespan

Add `enable_tracing()` as the **first call** inside the `lifespan()` async context manager, before any agent initialization:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    enable_tracing()       # <-- ADD THIS LINE

    # ... existing agent initialization code ...
    yield
    # ... existing cleanup code ...
```

This placement ensures tracing is configured before any autolog-patched code runs.

### 4. Wire `wrap_func_with_mlflow_trace` (Level B and C only)

Skip this step for Level A — autolog handles everything.

For Level B/C, you need to wrap agent and tool functions with trace spans. **Where** you add the wrapping depends on how the agent initializes its components. Read the agent's code to find:

#### Tool wrapping
Find where tools are registered or instantiated. Wrap each tool's callable:

**Pattern 1 — Tool objects with `_run` method (CrewAI-style, Level B):**
```python
# In crew.py or wherever tools are created
tool._run = wrap_func_with_mlflow_trace(tool._run, span_type="tool", name=tool.name)
```

**Pattern 2 — Tool functions registered by name (Vanilla Python-style, Level C):**
```python
# In agent.py or main.py, wherever tools are registered
func = wrap_func_with_mlflow_trace(func, span_type="tool")
agent.register_tool(name, func)
```

#### Agent orchestration wrapping
Find the main agent entry point (the function that runs the full agent loop) and wrap it:

```python
agent.query = wrap_func_with_mlflow_trace(agent.query, span_type="agent")
# or
agent.run = wrap_func_with_mlflow_trace(agent.run, span_type="agent")
```

#### Streaming path
Check if `_handle_stream` in `main.py` creates the agent differently from `_handle_chat`. If it does (e.g., creates a new agent instance directly instead of using the closure), the wrapping must be duplicated in the streaming path.

Reference: In the Vanilla Python agent, `_handle_stream` creates `AIAgent` directly and wraps tools + `agent.query` inside the `run_agent()` function. See `agents/vanilla_python/openai_responses_agent/main.py`, search for `def run_agent()`.

## Reference Files

Read these to see the wiring patterns in practice:
- `agents/vanilla_python/openai_responses_agent/main.py` — Level C wiring (search for `import enable_tracing`, `enable_tracing()` in `lifespan()`, and `run_agent()` in `_handle_stream`)
- `agents/langgraph/react_agent/main.py` — Level A wiring (search for `import enable_tracing` and `enable_tracing()` in `lifespan()`)
- `agents/crewai/websearch_agent/main.py` — Level B wiring (search for `import enable_tracing` and `enable_tracing()` in `lifespan()`)
- `agents/crewai/websearch_agent/src/crewai_web_search/crew.py` — Level B tool wrapping (search for `wrap_func_with_mlflow_trace` in `ai_assistant()`)

## Final Checklist

- [ ] `enable_tracing()` is called **before** agent initialization in `lifespan()`
- [ ] Import statement is at the top of `main.py` with other package imports
- [ ] For Level B/C: `wrap_func_with_mlflow_trace` is imported
- [ ] For Level B/C: Both streaming and non-streaming paths have wrapping applied
- [ ] No MLflow imports are added directly to `main.py` — all MLflow interaction goes through `tracing.py`

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
