---
name: add-manual-tracing
description: Adds manual MLflow trace wrapping for tool and agent spans in Level B and C agents where autolog doesn't cover everything.
argument-hint: "<agent_path>"
disable-model-invocation: true
---

# Add Manual Tracing (Level B and C)

> **Usage:** `/add-manual-tracing <agent_path>`
> **Example:** `/add-manual-tracing agents/autogen/chat_agent`

You are adding manual `wrap_func_with_mlflow_trace()` calls to an agent template where autolog does not fully cover all tracing layers.

**This skill is only for Level B (partial autolog) and Level C (no framework autolog).** If the framework is Level A, skip this skill entirely — autolog handles everything.

## Input

The agent path is: $ARGUMENTS

You also need the **package name**, **coverage level** (B or C), and **autolog support report**. If not provided, determine the package name from `pyproject.toml` or `src/`, and the coverage level from the agent's `tracing.py`.

## Steps

### 1. Read the agent's code

Read these files to understand how the agent works:
- `<agent_path>/main.py` — FastAPI app, `_handle_chat`, `_handle_stream`
- `<agent_path>/src/<package>/agent.py` — Agent class/factory, how tools are registered, the main entry point
- `<agent_path>/src/<package>/tools.py` — Tool function definitions
- Any other file where the agent or tools are assembled (e.g., `crew.py` for CrewAI)

Identify:
- **The agent entry point**: The function that runs the full agent loop (e.g., `agent.query()`, `agent.run()`, `crew.kickoff()`)
- **Tool registration**: How tools are attached to the agent (function list, tool objects, decorator-based, etc.)
- **Streaming vs non-streaming**: Whether the streaming path creates the agent differently

### 2. Determine what needs manual wrapping

Compare the autolog report with the three tracing layers:

| Layer | Needs manual wrapping if... |
|---|---|
| Agent orchestration | Autolog doesn't create a parent AGENT span for the full request |
| Tool execution | Autolog doesn't capture tool calls with TOOL spans |
| LLM calls | Autolog doesn't capture model API calls (rare — usually covered by provider autolog) |

### 3. Add tool wrapping

Wrap each tool so its execution creates a TOOL span. The wrapping location depends on how the agent registers tools:

**If tools are functions registered by name (common in Level C):**

In `agent.py` or wherever tools are registered (e.g., `from openai_responses_agent.tracing import wrap_func_with_mlflow_trace`):
```python
from <package>.tracing import wrap_func_with_mlflow_trace

# Wrap each tool function before registering
for name, func in self._tools:
    func = wrap_func_with_mlflow_trace(func, span_type="tool")
    agent.register_tool(name, func)
```

**If tools are class instances with a `_run` method (common in Level B, e.g., CrewAI):**

In the file where tool objects are created, e.g., `crew.py` (e.g., `from crewai_web_search.tracing import wrap_func_with_mlflow_trace`):
```python
from <package>.tracing import wrap_func_with_mlflow_trace

tools = [MyTool()]
for tool in tools:
    tool._run = wrap_func_with_mlflow_trace(tool._run, span_type="tool", name=tool.name)
```

**If tools are decorated functions (e.g., `@tool` decorator):**

Wrap the underlying function after the agent is assembled:
```python
from <package>.tracing import wrap_func_with_mlflow_trace

for tool in agent.tools:
    tool.func = wrap_func_with_mlflow_trace(tool.func, span_type="tool")
```

### 4. Add agent orchestration wrapping

Wrap the main agent entry point to create a parent AGENT span that groups all LLM calls and tool calls under one trace.

**In `agent.py` (preferred — wrap inside the adapter/closure):**
```python
agent.query = wrap_func_with_mlflow_trace(agent.query, span_type="agent")
```

**Or in `main.py` if the agent is created directly there:**
```python
# In _handle_chat:
agent = get_agent()
agent.run = wrap_func_with_mlflow_trace(agent.run, span_type="agent")
result = await agent.run(input=messages)
```

### 5. Handle the streaming path

This is critical. Read `_handle_stream` in `main.py` carefully.

**If streaming uses the same agent instance as non-streaming** (goes through the same closure/adapter):
- No extra work — the wrapping from step 3-4 applies to both paths.

**If streaming creates a new agent instance directly** (bypasses the adapter):
- You MUST duplicate the wrapping inside the streaming path.
- This is the pattern used by the Vanilla Python agent. See the `run_agent()` function inside `_handle_stream` in `agents/vanilla_python/openai_responses_agent/main.py`:

```python
# Inside _handle_stream's run_agent():
def run_agent():
    adapter = get_agent()
    agent = SomeAgent(model=adapter._model_id, ...)

    # Wrap tools
    for name, func in adapter._tools:
        func = wrap_func_with_mlflow_trace(func, span_type="tool")
        agent.register_tool(name, func)

    # Wrap agent entry point
    agent.query = wrap_func_with_mlflow_trace(agent.query, span_type="agent")

    return agent.query(user_message, ...)
```

**Why this matters:** Without a parent AGENT span, `mlflow.<provider>.autolog()` creates a separate trace for every LLM call instead of grouping them under one trace. This results in N traces per request instead of 1.

### 6. Verify wrapping is conditional

Confirm that `wrap_func_with_mlflow_trace()` in `tracing.py` returns the original function unchanged when `MLFLOW_TRACKING_URI` is not set. This means the wrapping calls in agent code are always safe — they're no-ops when tracing is disabled.

## Reference Files

- **Level B tool wrapping**: `agents/crewai/websearch_agent/src/crewai_web_search/crew.py` — `ai_assistant()` method
- **Level C tool + agent wrapping (non-streaming)**: `agents/vanilla_python/openai_responses_agent/src/openai_responses_agent/agent.py` — `_AIAgentAdapter.run()` method
- **Level C streaming path wrapping**: `agents/vanilla_python/openai_responses_agent/main.py` — `run_agent()` inside `_handle_stream()`

## Final Checklist

- [ ] Every tool function/method is wrapped with `span_type="tool"`
- [ ] The main agent entry point is wrapped with `span_type="agent"`
- [ ] Both streaming and non-streaming paths have wrapping applied
- [ ] Wrapping is safe when tracing is disabled (no-op via `wrap_func_with_mlflow_trace`)
- [ ] No duplicate wrapping — each function is wrapped exactly once per request
- [ ] The `name` parameter is used when wrapping tool objects (so span names are meaningful, not `_run`)

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
