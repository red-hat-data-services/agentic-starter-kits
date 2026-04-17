# MLflow Tracing Integration

This document covers how MLflow tracing is integrated into the agent templates in this repository: how it works, how it differs per framework, how to configure it, how to test it, and known issues.

---

## Table of Contents

- [Overview](#overview)
- [Design Principles](#design-principles)
- [Architecture](#architecture)
  - [Tracing Module (`tracing.py`)](#tracing-module-tracingpy)
  - [Startup Flow](#startup-flow)
  - [Graceful Degradation](#graceful-degradation)
- [Framework-Specific Integration](#framework-specific-integration)
  - [Vanilla Python (OpenAI Responses)](#vanilla-python-openai-responses)
  - [LangGraph](#langgraph)
  - [LlamaIndex](#llamaindex)
  - [CrewAI](#crewai)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Local Setup](#local-setup)
  - [OpenShift Cluster Setup](#openshift-cluster-setup)
- [Tracing Layers](#tracing-layers)
- [Testing Tracing](#testing-tracing)
  - [Pre-Test Checklist](#pre-test-checklist)
  - [Step-by-Step Verification](#step-by-step-verification)
  - [What to Verify in Traces](#what-to-verify-in-traces)
- [Google ADK](#google-adk)
- [Known Issues & Gotchas](#known-issues--gotchas)

---

## Overview

Each agent template optionally integrates with [MLflow](https://mlflow.org/) for tracing LLM calls, tool executions, and agent orchestration. Tracing is **opt-in**: if `MLFLOW_TRACKING_URI` is not set, the agent runs normally without any MLflow dependency.

MLflow is listed as an **optional dependency** in each agent's `pyproject.toml` under a `tracing` extra. When `MLFLOW_TRACKING_URI` is set, `make run` auto-installs it via `uv run --extra tracing`. Users can also start the MLflow server with:

```bash
uv run --extra tracing mlflow server --port 5000
```

This keeps MLflow out of the core dependencies — agents run without it when tracing is disabled.

---

## Design Principles

1. **Opt-in by environment variable** — `MLFLOW_TRACKING_URI` is the single switch. No code changes needed to enable/disable tracing.
2. **Graceful degradation** — If the MLflow server is unreachable at startup, the agent logs a warning and continues without tracing.
3. **Fail-fast on missing package** — If `MLFLOW_TRACKING_URI` is set but MLflow is not installed, the agent fails at startup with a clear error. MLflow imports are inside `enable_tracing()` (not at module top) so the module can be imported without MLflow — but once tracing is requested, the package must be present.
4. **Framework-native auto-tracing where possible** — Most frameworks have an MLflow autolog integration (`mlflow.langchain`, `mlflow.llama_index`, `mlflow.crewai`, `mlflow.openai`) that automatically captures spans. Some frameworks (Google ADK) natively emit OpenTelemetry spans instead, which MLflow ingests via OTLP.
5. **Manual tracing only where auto-tracing falls short** — Manual `wrap_func_with_mlflow_trace()` is used only where autolog doesn't capture what's needed (e.g., Vanilla Python agent orchestration, CrewAI tool spans).

---

## Architecture

### Tracing Module (`tracing.py`)

Every agent has a `tracing.py` module at `src/<package_name>/tracing.py` that exports two main functions:

#### `enable_tracing()`

Called once during FastAPI `lifespan` startup. Responsible for:
1. Loading `.env` via `load_dotenv()`
2. Checking if `MLFLOW_TRACKING_URI` is set (if not, tracing is skipped)
3. Health-checking the MLflow server with retry logic
4. Configuring MLflow: `set_tracking_uri()`, `set_experiment()`, `enable_async_logging()`
5. Enabling framework-specific autolog (the **only part that differs** between agents)

#### `wrap_func_with_mlflow_trace(func, span_type, name=None)`

Wraps a callable with `mlflow.trace()` to create a named span. Used for manual tracing where autolog doesn't cover. Returns the original function unchanged if `MLFLOW_TRACKING_URI` is not set.

- `span_type="tool"` creates a `SpanType.TOOL` span
- `span_type="agent"` creates a `SpanType.AGENT` span

Only present in agents that need manual tracing (Vanilla Python and CrewAI). LangGraph and LlamaIndex rely entirely on autolog.

#### `check_mlflow_health(mlflow_tracking_uri, max_wait_time, retry_interval)`

Polls `{mlflow_tracking_uri}/health` with retry logic. Raises `RuntimeError` if the server is unreachable after `max_wait_time` seconds. The timeout for each individual HTTP request is capped at `min(5, remaining_budget)` to respect the overall time budget.

### Startup Flow

```text
FastAPI lifespan start
  |
  v
enable_tracing()
  |
  +-- MLFLOW_TRACKING_URI not set? --> log info, return (tracing disabled)
  |
  +-- Health check MLflow server (retry for MLFLOW_HEALTH_CHECK_TIMEOUT seconds)
  |     |
  |     +-- Server unreachable? --> log warning, return (tracing disabled, agent continues)
  |     |
  |     +-- Server reachable? --> continue
  |
  +-- mlflow.set_tracking_uri(...)
  +-- mlflow.set_experiment(...)
  +-- mlflow.config.enable_async_logging()
  +-- mlflow.<framework>.autolog()     <-- framework-specific
  |
  v
Agent initialization (get_agent_closure / get_graph_closure / etc.)
```

### Graceful Degradation

The tracing system is designed to never prevent the agent from starting:

| Scenario | Behavior |
|---|---|
| `MLFLOW_TRACKING_URI` not set | Tracing silently disabled. No MLflow imports. |
| `MLFLOW_TRACKING_URI` set but server unreachable | Warning logged, tracing disabled, agent starts normally. |
| `MLFLOW_TRACKING_URI` set and server reachable | Tracing fully enabled. |
| MLflow package not installed but `MLFLOW_TRACKING_URI` set | `ImportError` will occur. MLflow must be installed if the env var is set. |

---

## Framework-Specific Integration

### Vanilla Python (OpenAI Responses)

**Autolog:** `mlflow.openai.autolog()`
**Manual tracing:** Yes (`wrap_func_with_mlflow_trace` for agent + tool spans)

This agent has no framework-level orchestration, so autolog only captures raw OpenAI `responses.create()` calls. Manual wrapping adds the orchestration layer:

**Non-streaming (`_handle_chat` in `main.py`):**
- `_AIAgentAdapter.run()` in `agent.py` wraps `agent.query()` with `span_type="agent"` and each tool function with `span_type="tool"`

**Streaming (`_handle_stream` in `main.py`):**
- Creates `AIAgent` directly (bypasses `_AIAgentAdapter`) and manually applies the same wrapping:
  ```python
  for name, func in adapter._tools:
      func = wrap_func_with_mlflow_trace(func, span_type="tool")
      agent.register_tool(name, func)
  agent.query = wrap_func_with_mlflow_trace(agent.query, span_type="agent")
  ```

**Resulting spans:**

| Span Name | Type | Source |
|---|---|---|
| `query` | AGENT | Manual (`wrap_func_with_mlflow_trace`) |
| `Responses` | CHAT_MODEL | `mlflow.openai.autolog()` (one per LLM call in the ReAct loop) |
| `search_price`, `search_reviews` | TOOL | Manual (`wrap_func_with_mlflow_trace`) |

### LangGraph

**Autolog:** `mlflow.langchain.autolog()`
**Manual tracing:** None needed

LangChain's autolog captures the full execution graph including LLM calls, tool calls, and agent orchestration. Works with both `ainvoke` (non-streaming) and `astream_events` (streaming).

**Resulting spans:**

| Span Name | Type | Source |
|---|---|---|
| `LangGraph` | CHAIN | `mlflow.langchain.autolog()` |
| `ChatOpenAI` | CHAT_MODEL | `mlflow.langchain.autolog()` |
| `tools` | CHAIN | `mlflow.langchain.autolog()` |
| `dummy_web_search` | TOOL | `mlflow.langchain.autolog()` |

No `LLM_PROVIDER` env var needed — `ChatOpenAI` is a LangChain component and is fully traced by langchain autolog regardless of the underlying `base_url`.

### LlamaIndex

**Autolog:** `mlflow.llama_index.autolog()`
**Manual tracing:** None needed

LlamaIndex's autolog captures the full workflow including agent runs, LLM chats, and tool calls.

**Resulting spans:**

| Span Name | Type | Source |
|---|---|---|
| `FunctionCallingAgent.run` | CHAIN | `mlflow.llama_index.autolog()` |
| `OpenAILike.achat` | CHAT_MODEL | `mlflow.llama_index.autolog()` |
| `FunctionTool` | TOOL | `mlflow.llama_index.autolog()` |

No `LLM_PROVIDER` env var needed — `OpenAILike` is a LlamaIndex component, fully traced.

### CrewAI

**Autolog:** `mlflow.crewai.autolog()` + provider-specific autolog
**Manual tracing:** Yes (tool `_run` methods in `crew.py`)

CrewAI is the most complex integration because it has two layers that need separate autologs:

#### Layer 1: Orchestration (`mlflow.crewai.autolog()`)
Captures Crew, Task, and Agent spans. However, in newer CrewAI versions (>=1.10), **tool spans are not captured by autolog**. This is why tools are manually wrapped in `crew.py`:

```python
# crew.py
for tool in tools:
    tool._run = wrap_func_with_mlflow_trace(tool._run, span_type="tool", name=tool.name)
```

#### Layer 2: LLM calls (provider-specific autolog)
CrewAI has a factory pattern (`LLM.__new__`) that routes to different provider backends. Native providers (OpenAI, Anthropic, Gemini, Azure, Bedrock) bypass the `crewai.LLM.call` method that `mlflow.crewai.autolog()` patches, so a second provider-specific autolog is needed.

The `LLM_PROVIDER` env var controls which autolog is enabled:

| `LLM_PROVIDER` | Autolog Module | When to Use |
|---|---|---|
| `litellm` (default) | `mlflow.litellm` | Non-native models going through LiteLLM fallback |
| `openai` | `mlflow.openai` | Native OpenAI models (e.g., `gpt-4o-mini`) |
| `anthropic` | `mlflow.anthropic` | Native Anthropic models |
| `gemini` | `mlflow.gemini` | Native Google Gemini models |
| `azure` | `mlflow.openai` | Azure OpenAI models |
| `bedrock` | `mlflow.bedrock` | AWS Bedrock models |

**How the factory pattern determines the provider path:**
- `openai/gpt-4o-mini` (recognized model) -> `OpenAICompletion` (native, bypasses `LLM.call`)
- `openai/my-custom-model` (unrecognized) -> base `LLM` class (LiteLLM fallback)

**Resulting spans:**

| Span Name | Type | Source |
|---|---|---|
| `CrewAI` | AGENT | `mlflow.crewai.autolog()` |
| `Task` | CHAIN | `mlflow.crewai.autolog()` |
| `Agent` | AGENT | `mlflow.crewai.autolog()` |
| `WebSearchTool` | TOOL | Manual (`wrap_func_with_mlflow_trace` in `crew.py`) |
| `Completions` or `litellm-completion` | CHAT_MODEL / LLM | Provider-specific autolog |

### Google ADK

**Autolog:** None — uses OpenTelemetry-based auto-tracing
**Manual tracing:** None needed

Google ADK is architecturally unique among the agents in this repo. There is no `mlflow.google_adk.autolog()` module. Instead, ADK natively emits OpenTelemetry spans for agent runs, tool calls, and model requests. We configure an OTLP exporter to forward those spans to the MLflow tracking server.

This makes it **Level A** in terms of coverage (all three layers captured automatically), but the mechanism is different from LangGraph/LlamaIndex which use `mlflow.<framework>.autolog()`.

#### Setup Differences

1. **OpenTelemetry exporter required**: `tracing.py` sets up a `TracerProvider` with an `OTLPSpanExporter` pointing at `{tracking_uri}/v1/traces`, instead of calling an autolog function.
2. **SQL backend required**: The MLflow server must be started with `--backend-store-uri sqlite:///mlflow.db` (or another SQL store). File-based backend stores do not support OTLP ingestion.
3. **Extra package**: `opentelemetry-exporter-otlp-proto-http` must be installed alongside MLflow.
4. **Experiment ID header**: The OTLP exporter sends the experiment ID via the `x-mlflow-experiment-id` HTTP header, which is obtained from `mlflow.set_experiment()`.

#### How It Works

```python
# In enable_tracing() — instead of mlflow.<framework>.autolog()
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

exporter = OTLPSpanExporter(
    endpoint=f"{tracking_uri}/v1/traces",
    headers={"x-mlflow-experiment-id": experiment.experiment_id},
)
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
```

The `TracerProvider` must be set **before** any ADK components are used (i.e., `enable_tracing()` is called first in the lifespan, before `get_runner()`).

**Resulting spans:**

| Span Name | Type | Source |
|---|---|---|
| `invocation` | — | ADK OTel (top-level request) |
| `invoke_agent adk_agent` | AGENT | ADK OTel |
| `generate_content openai/<model>` | LLM | ADK OTel |
| `call_llm` | LLM | ADK OTel |
| `execute_tool search_price` | TOOL | ADK OTel |

No `LLM_PROVIDER` env var needed — ADK traces LLM calls through its own instrumentation regardless of the underlying model connector (LiteLLM, Gemini, etc.).

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MLFLOW_TRACKING_URI` | *(unset)* | MLflow server URL. Setting this enables tracing. |
| `MLFLOW_EXPERIMENT_NAME` | `default-agent-experiment` | Experiment name for organizing traces. |
| `MLFLOW_HEALTH_CHECK_TIMEOUT` | `5` | Seconds to wait for MLflow server at startup. |
| `MLFLOW_HTTP_REQUEST_TIMEOUT` | `120` (MLflow default) | Timeout for MLflow HTTP requests during operation. |
| `MLFLOW_HTTP_REQUEST_MAX_RETRIES` | MLflow default | Max retries for MLflow HTTP requests. |
| `LLM_PROVIDER` | `litellm` | **CrewAI only.** Which provider autolog to enable. |
| `MLFLOW_TRACKING_TOKEN` | *(unset)* | **OpenShift only.** Auth token for MLflow on OpenShift. |
| `MLFLOW_TRACKING_INSECURE_TLS` | *(unset)* | **OpenShift only.** Set `"true"` for self-signed certs. |
| `MLFLOW_WORKSPACE` | *(unset)* | **OpenShift only.** Project/workspace name. |
| `MLFLOW_TRACKING_AUTH` | *(unset)* | **OpenShift only.** Use K8s service account auth. |

### Local Setup

Add to your agent's `.env` file:

```ini
MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="My Agent Experiment"
MLFLOW_HEALTH_CHECK_TIMEOUT=5
MLFLOW_HTTP_REQUEST_TIMEOUT=2
MLFLOW_HTTP_REQUEST_MAX_RETRIES=0
```

Start the MLflow server:

```bash
mlflow server --port 5000
```

### OpenShift Cluster Setup

```ini
MLFLOW_TRACKING_URI="https://<openshift-dashboard-url>/mlflow"
MLFLOW_TRACKING_TOKEN="<your-openshift-token>"
MLFLOW_EXPERIMENT_NAME="<your-experiment-name>"
MLFLOW_TRACKING_INSECURE_TLS="true"
MLFLOW_WORKSPACE="default"
```

---

## Tracing Layers

Every agent's traces consist of up to three layers. Which layers are present depends on the framework:

```text
+--------------------------------------------------+
|  Layer 3: Agent Orchestration                     |
|  (Agent loop, Tasks, Crew)                        |
|  Source: framework autolog or manual wrapping      |
|                                                    |
|  +----------------------------------------------+ |
|  |  Layer 2: Tool Execution                     | |
|  |  (search_price, dummy_web_search, etc.)      | |
|  |  Source: framework autolog or manual wrapping | |
|  |                                               | |
|  |  +------------------------------------------+| |
|  |  |  Layer 1: LLM Calls                      || |
|  |  |  (responses.create, chat.completions)     || |
|  |  |  Source: provider autolog                 || |
|  |  +------------------------------------------+| |
|  +----------------------------------------------+ |
+--------------------------------------------------+
```

| Framework | Layer 1 (LLM) | Layer 2 (Tools) | Layer 3 (Orchestration) |
|---|---|---|---|
| **Vanilla Python** | `mlflow.openai.autolog()` | Manual wrapping | Manual wrapping |
| **LangGraph** | `mlflow.langchain.autolog()` | Same autolog | Same autolog |
| **LlamaIndex** | `mlflow.llama_index.autolog()` | Same autolog | Same autolog |
| **CrewAI** | Provider-specific autolog | Manual wrapping | `mlflow.crewai.autolog()` |
| **Google ADK** | ADK OTel auto-tracing | ADK OTel auto-tracing | ADK OTel auto-tracing |

### Autolog Coverage Levels

The amount of tracing code required for a new agent depends on how well MLflow's autolog supports the framework. We classify frameworks into three levels:

**Level A — Full auto-tracing.** All three layers are captured automatically with no manual wrapping needed. `tracing.py` only contains `enable_tracing()` and no `wrap_func_with_mlflow_trace()` function. There are two variants:
- **Autolog variant**: `mlflow.<framework>.autolog()` captures everything. Examples: LangGraph (`mlflow.langchain`), LlamaIndex (`mlflow.llama_index`).
- **OpenTelemetry variant**: The framework natively emits OTel spans; `tracing.py` sets up an OTLP exporter to forward them to MLflow. Requires a SQL-based MLflow backend and `opentelemetry-exporter-otlp-proto-http`. Example: Google ADK.

**Level B — Partial autolog.** `mlflow.<framework>.autolog()` exists but misses one or more layers (typically tool spans). `tracing.py` includes both `enable_tracing()` (with framework + provider autologs) and `wrap_func_with_mlflow_trace()`. Tool functions are wrapped manually in the agent's code. Example in this repo: CrewAI — `mlflow.crewai.autolog()` captures orchestration but not tool spans, and a separate provider autolog is needed for LLM calls.

**Level C — No framework autolog.** No `mlflow.<framework>` module exists. `tracing.py` includes `enable_tracing()` (with provider autolog only) and `wrap_func_with_mlflow_trace()`. Both tool functions and the agent entry point must be wrapped manually. Example in this repo: Vanilla Python — only `mlflow.openai.autolog()` is available for LLM calls.

| Level | `enable_tracing()` | `wrap_func_with_mlflow_trace()` | Manual wrapping needed for |
|-------|--------------------|---------------------------------|---------------------------|
| A | Framework autolog | Not created | Nothing |
| B | Framework + provider autolog | Created | Tools |
| C | Provider autolog only | Created | Tools + agent entry point |

To check a new framework's level, search the [MLflow autolog integrations page](https://mlflow.org/docs/latest/genai/tracing/integrations/).

---

## Testing Tracing

### Pre-Test Checklist

1. **Agent tools**: Read `crew.py` / `agent.py` / `tools.py` to understand available tools and their dummy responses. Craft test messages that will trigger tool calls.
2. **Experiment name**: Check `.env` for `MLFLOW_EXPERIMENT_NAME`.
3. **App port**: Confirm the port (default 8000).
4. **MLflow URL**: Confirm MLflow server URL (default `http://localhost:5000`).
5. **LLM provider** (CrewAI only): Check `LLM_PROVIDER` in `.env`.

### Step-by-Step Verification

**1. Send a request to the agent:**

```bash
# Non-streaming
curl -s -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "How much does a Lenovo laptop cost?"}], "stream": false}' | python3 -m json.tool

# Streaming
curl -s -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "How much does a Lenovo laptop cost?"}], "stream": true}'
```

**2. Get experiment ID:**

```bash
curl -s "http://localhost:5000/api/2.0/mlflow/experiments/get-by-name?experiment_name=<NAME>" \
  | python3 -m json.tool
```

**3. Get latest trace metadata:**

```bash
curl -s "http://localhost:5000/api/2.0/mlflow/traces?experiment_ids=<ID>&max_results=1" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
t = data['traces'][0]
meta = {m['key']: m['value'] for m in t['request_metadata']}
print('Trace:', t['request_id'])
print('Spans:', json.loads(meta.get('mlflow.trace.sizeStats', '{}')).get('num_spans'))
print('Tokens:', meta.get('mlflow.trace.tokenUsage'))
"
```

**4. Inspect individual spans:**

```python
import mlflow
mlflow.set_tracking_uri("http://localhost:5000")
trace = mlflow.get_trace("<trace-id>")
for span in trace.search_spans():
    print(f"  {span.name} (type: {span.span_type})")
```

### What to Verify in Traces

- **Orchestration spans** exist (agent/crew/graph level)
- **Tool spans** appear with correct names and inputs/outputs
- **LLM spans** capture the model calls with content
- **Token usage** appears in trace metadata (if LLM spans are captured)
- **Single trace per request** — all spans grouped under one trace, not scattered across multiple
- **Streaming and non-streaming produce equivalent traces** (same span structure)

---

## Known Issues & Gotchas

### CrewAI: Tool spans not captured by autolog (>=1.10)
`mlflow.crewai.autolog()` does not capture tool spans in newer CrewAI versions. Tools are manually wrapped in `crew.py` via `wrap_func_with_mlflow_trace(tool._run, span_type="tool", name=tool.name)`. If a future CrewAI/MLflow version fixes this, remove the manual wrapping to avoid duplicate spans.

### CrewAI: Native providers bypass `LLM.call` patch
CrewAI's `LLM.__new__` factory returns provider-specific subclasses (`OpenAICompletion`, `AnthropicCompletion`, etc.) that inherit from `BaseLLM`, not `LLM`. Since `mlflow.crewai.autolog()` patches `crewai.LLM.call`, these native subclasses bypass the patch entirely. This is why a separate provider-specific autolog (`mlflow.openai.autolog()`, etc.) is required via the `LLM_PROVIDER` env var.

### CrewAI: Hardcoded `openai/` prefix
`main.py` hardcodes `model=f"openai/{model_id}"`, which means CrewAI's factory decides the provider path based on whether it recognizes the model name — not user intent. `openai/gpt-4o-mini` goes native OpenAI; `openai/my-custom-model` falls back to LiteLLM. Users who want to use non-OpenAI providers need to edit `main.py`.

### Vanilla Python: Streaming required a separate tracing fix
The streaming path (`_handle_stream`) creates `AIAgent` directly rather than going through `_AIAgentAdapter.run()`. Without explicit wrapping, `mlflow.openai.autolog()` creates separate traces per `responses.create()` call instead of grouping them under a single agent span. The fix manually applies `wrap_func_with_mlflow_trace` in the streaming path. This is specific to the Vanilla Python agent — LangGraph and LlamaIndex handle streaming tracing natively via their autologs.

### LangGraph/LlamaIndex: Empty `content` on tool call messages
When the LLM makes a function call, the `AIMessage.content` is empty (the call info is in `tool_calls`). This appears in traces as tool-call spans with no content text. This is correct function-calling API behavior, not a tracing issue.

### Google ADK: Requires SQL-based MLflow backend
Google ADK's tracing uses OpenTelemetry OTLP ingestion, which is only supported with SQL-based backend stores (SQLite, PostgreSQL, MySQL). The default file-based backend (`mlflow server --port 5000`) does not work. Start with `mlflow server --backend-store-uri sqlite:///mlflow.db --port 5000`. This only affects Google ADK — all other agents work with file-based backends.

### Google ADK: Extra package required for tracing
In addition to MLflow, Google ADK tracing requires `opentelemetry-exporter-otlp-proto-http` to be installed. Without it, `enable_tracing()` will log a warning (`"MLflow or OpenTelemetry packages not installed"`) and continue without tracing.

### MLflow must be installed if `MLFLOW_TRACKING_URI` is set
MLflow imports are inside `enable_tracing()`, so the agent starts fine without MLflow when `MLFLOW_TRACKING_URI` is not set. But if the URI is set, `enable_tracing()` will fail at startup with a clear `ModuleNotFoundError` telling the user to install MLflow. This is intentional — silently skipping tracing when the user explicitly requested it would hide a misconfiguration.
