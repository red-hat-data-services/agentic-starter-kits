---
name: test-tracing
description: Tests MLflow tracing end-to-end by starting servers, sending requests, and verifying spans appear correctly in the MLflow API.
argument-hint: "<agent_path>"
disable-model-invocation: true
---

# Test MLflow Tracing

> **Usage:** `/test-tracing <agent_path>`
> **Example:** `/test-tracing agents/langgraph/react_agent`

You are testing that MLflow tracing is working correctly for an agent template — verifying that traces land in the MLflow server with the expected spans.

**You must execute every step yourself.** Run all commands, start all servers, send all requests, and query all APIs. Do not tell the user to do any of this manually. Do not stop partway and summarize remaining steps. You own the entire testing workflow end-to-end.

## Input

The agent path is: $ARGUMENTS

If no agent path was provided, ask the user which agent they want to test.

## Pre-Test Checklist

Before sending any requests, gather this information by reading the agent's files:

1. **Agent tools**: Read the agent's `agent.py`, `crew.py`, or `tools.py` to understand what tools are available and what dummy responses they return. Craft test messages that will trigger tool calls.
2. **App port**: Confirm which port the agent is running on (check `.env` or ask the user). Default is `8000`.
3. **LLM provider** (CrewAI only): Check `LLM_PROVIDER` in `.env` to know which autolog to expect.
4. **Coverage level**: Know whether the agent uses Level A (full autolog), B (partial), or C (no framework autolog) — this determines what spans to expect.

## Step 1: Ensure MLflow is installed

Check if MLflow is available in the current Python environment:

```bash
python3 -c "import mlflow; print('MLflow version:', mlflow.__version__)"
```

If not installed, install it:

```bash
uv pip install "mlflow>=3.10.0"
```

## Step 2: Set up the agent's `.env`

Read the agent's `.env.example` to see what variables are needed:

```bash
cat <agent_path>/.env.example
```

Check if `<agent_path>/.env` already exists. If not, create it from the example:

```bash
cp <agent_path>/.env.example <agent_path>/.env
```

Ensure these tracing variables are set in `.env`:

```ini
MLFLOW_TRACKING_URI=http://localhost:<MLFLOW_PORT>
MLFLOW_EXPERIMENT_NAME=<descriptive-experiment-name>
```

For the LLM API key: check if `API_KEY` is already set in the shell environment:

```bash
echo $API_KEY
```

If not set, ask the user for it. Do not guess or skip — the agent won't work without it.

Confirm `BASE_URL` and `MODEL_ID` are also set in `.env`.

## Step 3: Start the MLflow server

Check if an MLflow server is already running:

```bash
curl -s http://localhost:<MLFLOW_PORT>/health
```

If not running, start one. Try port 5000 first; if occupied, increment:

```bash
mlflow server --port 5000
```

If port 5000 is occupied:

```bash
mlflow server --port 5001
```

Keep incrementing until you find an open port. Record the port as `<MLFLOW_PORT>` and make sure `MLFLOW_TRACKING_URI` in the agent's `.env` matches (e.g., `http://localhost:5001`).

**Use `http://localhost:<MLFLOW_PORT>` consistently for ALL MLflow API calls below.** Do not hardcode port 5000 — always use the actual port the server is running on.

**The MLflow server must keep running in the background.** Tell the user to keep that terminal open, or run it in the background.

## Step 4: Start the agent

Set up the environment and start the agent:

```bash
cd <agent_path>
make init              # Copy .env.example → .env (if .env doesn't exist)
# Edit .env with the correct values (API keys, MLflow URI, etc.)
source .env
uvicorn main:app --port <PORT>
```

**The agent must keep running in the background.** Tell the user to keep that terminal open, or run it in the background.

Verify the agent is healthy:

```bash
curl -s http://localhost:<PORT>/health | python3 -m json.tool
```

Expect: `{"status": "healthy", "agent_initialized": true}`

Check the agent's startup logs for the `[Tracing Enabled]` message confirming MLflow tracing is active. If you see `[Tracing] MLFLOW_TRACKING_URI not set` or `MLflow server is unreachable`, fix the `.env` or MLflow server before proceeding.

## Step 5: Get the experiment ID and record baseline trace count

Get the experiment ID first so you can track trace counts before and after test requests.

```bash
curl -s "http://localhost:<MLFLOW_PORT>/api/2.0/mlflow/experiments/get-by-name?experiment_name=<EXPERIMENT_NAME>" | python3 -m json.tool
```

Extract the `experiment_id` from the response. Then record how many traces exist before testing:

```bash
curl -s "http://localhost:<MLFLOW_PORT>/api/2.0/mlflow/traces?experiment_ids=<EXPERIMENT_ID>&max_results=0" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Traces before test:', len(data.get('traces', [])))
"
```

If the experiment doesn't exist yet (first run), the baseline is 0.

## Step 6: Send a test request (non-streaming)

Craft a message based on the agent's tools. The message should trigger at least one tool call so you can verify tool spans.

```bash
curl -s -X POST http://localhost:<PORT>/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "<message that triggers tools>"}], "stream": false}' | python3 -m json.tool
```

Verify the response has a valid `chat.completion` structure with an assistant message.

## Step 7: Verify exactly 1 new trace from non-streaming request

```bash
curl -s "http://localhost:<MLFLOW_PORT>/api/2.0/mlflow/traces?experiment_ids=<EXPERIMENT_ID>&max_results=5" | python3 -c "
import json, sys
data = json.load(sys.stdin)
traces = data.get('traces', [])
print('Total traces now:', len(traces))
print('Latest trace ID:', traces[0]['request_id'] if traces else 'NONE')
"
```

Compare with the baseline from Step 3. Exactly **1 new trace** should have appeared. If more than 1 appeared, the agent is producing fragmented traces (missing parent AGENT span — see Common Problems).

Record the non-streaming trace's `request_id`.

## Step 8: Send a test request (streaming)

```bash
curl -s -X POST http://localhost:<PORT>/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "<message that triggers tools>"}], "stream": true}'
```

Verify SSE chunks arrive with `chat.completion.chunk` objects, ending with `data: [DONE]`.

## Step 9: Verify exactly 1 new trace from streaming request

```bash
curl -s "http://localhost:<MLFLOW_PORT>/api/2.0/mlflow/traces?experiment_ids=<EXPERIMENT_ID>&max_results=5" | python3 -c "
import json, sys
data = json.load(sys.stdin)
traces = data.get('traces', [])
print('Total traces now:', len(traces))
print('Latest trace ID:', traces[0]['request_id'] if traces else 'NONE')
"
```

Exactly **1 more trace** should have appeared since Step 5. If more, streaming is producing fragmented traces.

Record the streaming trace's `request_id`.

## Step 10: Inspect spans for both traces

For each trace (non-streaming and streaming), inspect the individual spans.

First check if `mlflow` is available in the current Python environment:

```bash
python3 -c "import mlflow; print('MLflow available:', mlflow.__version__)"
```

If MLflow is available, inspect spans using the Python SDK:

```python
import mlflow
mlflow.set_tracking_uri("http://localhost:<MLFLOW_PORT>")

for label, trace_id in [("Non-streaming", "<non_streaming_trace_id>"), ("Streaming", "<streaming_trace_id>")]:
    print(f"\n{label} trace: {trace_id}")
    trace = mlflow.get_trace(trace_id)
    for span in trace.search_spans():
        print(f"  {span.name} (type: {span.span_type})")
```

If MLflow is not installed in the current env, use the REST API as a fallback:

```bash
curl -s "http://localhost:<MLFLOW_PORT>/api/2.0/mlflow/traces/<TRACE_ID>/spans" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for span in data.get('spans', []):
    print(f'  {span[\"name\"]} (type: {span[\"span_type\"]})')
"
```

## Step 11: Compare streaming and non-streaming traces

Both traces should have the **same span structure** — same span types and roughly the same span names. Compare:

- Same number of spans (or close — minor differences are acceptable)
- Same span types present (CHAIN, CHAT_MODEL, TOOL, AGENT)
- No missing layers in either trace

If streaming has fewer spans or is missing tool/agent spans, the streaming path is not properly traced — see the `add-manual-tracing` skill.

## Step 12: Validate the spans

Check the span output against expected patterns for the agent's coverage level:

### Level A (Full autolog — e.g., LangGraph, LlamaIndex)
Expected span types:
- CHAIN spans for orchestration (e.g., `LangGraph`, `FunctionCallingAgent.run`)
- CHAT_MODEL spans for LLM calls (e.g., `ChatOpenAI`, `OpenAILike.achat`)
- TOOL spans for tool calls (e.g., `dummy_web_search`)

### Level B (Partial autolog — e.g., CrewAI)
Expected span types:
- AGENT/CHAIN spans from framework autolog (e.g., `CrewAI`, `Task`, `Agent`)
- TOOL spans from manual wrapping (e.g., `WebSearchTool`)
- CHAT_MODEL or LLM spans from provider autolog (e.g., `Completions`, `litellm-completion`)

### Level C (No framework autolog — e.g., Vanilla Python)
Expected span types:
- AGENT span from manual wrapping (e.g., `query`)
- TOOL spans from manual wrapping (e.g., `search_price`, `search_reviews`)
- CHAT_MODEL spans from provider autolog (e.g., `Responses`)

## Common Problems and Fixes

| Problem | Symptom | Fix |
|---|---|---|
| Multiple traces per request | Span count is low (1-2), multiple trace IDs for one request | Missing parent AGENT span — add `wrap_func_with_mlflow_trace(agent.run, span_type="agent")` |
| No tool spans | Only LLM/orchestration spans visible | Tools not wrapped — add `wrap_func_with_mlflow_trace` for each tool |
| No LLM spans | Only orchestration/tool spans, no token usage | Wrong or missing provider autolog — check `LLM_PROVIDER` env var (CrewAI) or add `mlflow.<provider>.autolog()` |
| No traces at all | Experiment exists but no traces | Check agent startup logs for `[Tracing Enabled]` message. If missing, check `MLFLOW_TRACKING_URI` is set and MLflow is reachable. |
| Streaming creates separate traces | Non-streaming works fine, streaming produces N traces | Streaming path missing wrapping — see `add-manual-tracing` skill, streaming section |
| Token usage is null | Traces exist with spans but no token counts | LLM span not capturing usage — provider autolog may not support it for this model/endpoint |

## Output

Report the results:

```text
## Tracing Test Report: <agent_name>

**MLflow URL**: <mlflow_url>
**Experiment name**: <experiment_name>
**Test query used**: "<the message sent to the agent>"

### Non-streaming
**Request**: PASS / FAIL
**Trace appeared in MLflow**: YES / NO
**Traces produced**: <number> (expected: 1)
**Span count**: <number>
**Span breakdown**:
  - <span_name> (<span_type>) — <source: autolog or manual>
  - ...

### Streaming
**Request**: PASS / FAIL
**Trace appeared in MLflow**: YES / NO
**Traces produced**: <number> (expected: 1)
**Span count**: <number>
**Span breakdown**:
  - <span_name> (<span_type>) — <source: autolog or manual>
  - ...

### Comparison
**Streaming and non-streaming span structures match**: YES / NO

### Summary
**Token usage captured**: YES / NO
**Issues found**: <list or "None">
```

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
