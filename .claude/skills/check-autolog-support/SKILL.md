---
name: check-autolog-support
description: Researches and classifies a framework's MLflow autolog support level (A, B, or C) to determine what manual tracing is needed.
argument-hint: "<framework>"
disable-model-invocation: true
---

# Check MLflow Autolog Support for a Framework

> **Usage:** `/check-autolog-support <framework>`
> **Example:** `/check-autolog-support autogen`

You are determining whether MLflow has autolog support for a given agent framework, and what that autolog covers.

## Input

The framework name is: $ARGUMENTS

If no framework name was provided, ask the user which framework they want to check.

## Steps

### 1. Search MLflow's autolog modules

First, check the official MLflow autolog integrations page for the list of supported frameworks and model providers:
https://mlflow.org/docs/latest/genai/tracing/integrations/

Then, if needed, use WebSearch to find additional details about `mlflow.<framework>.autolog()`:
- `mlflow <framework> autolog`
- Check the MLflow documentation and GitHub repo for `mlflow/<framework>` module

### 2. Classify the autolog coverage level

Based on your research, classify the framework into one of these levels:

**Level A — Full auto-tracing**: All three tracing layers are captured automatically:
- Agent/orchestration spans (agent loops, workflows, task execution)
- Tool execution spans (tool calls with inputs/outputs)
- LLM call spans (model API calls with token usage)

There are two variants:
- **Autolog variant**: `mlflow.<framework>.autolog()` captures everything. Examples: LangGraph (`mlflow.langchain`), LlamaIndex (`mlflow.llama_index`)
- **OTel variant**: No `mlflow.<framework>.autolog()` exists, but the framework natively emits OpenTelemetry spans that MLflow ingests via OTLP. Requires SQL-based MLflow backend and `opentelemetry-exporter-otlp-proto-http`. Example: Google ADK

**Level B — Partial autolog**: `mlflow.<framework>.autolog()` exists but misses one or more layers. Common gaps:
- Tool spans not captured (CrewAI >=1.10)
- LLM calls routed through a different provider path not covered by the framework autolog
- Only orchestration-level spans, no LLM-level detail

Example in this repo: CrewAI (`mlflow.crewai` covers orchestration, but tools need manual wrapping and LLM calls need a separate provider-specific autolog)

**Level C — No framework autolog**: No `mlflow.<framework>` module exists. All tracing must be done manually using `mlflow.trace()` decorators, but you can still use a provider-level autolog for LLM calls (e.g., `mlflow.openai.autolog()` if the framework uses the OpenAI SDK under the hood).

Example in this repo: Vanilla Python agent (uses `mlflow.openai.autolog()` for LLM calls, manual wrapping for agent loop + tools)

### 3. Identify the LLM provider path

Determine how the framework makes LLM calls:
- Does it use the OpenAI SDK directly? → `mlflow.openai.autolog()` can capture LLM spans
- Does it use LangChain's `ChatOpenAI`? → `mlflow.langchain.autolog()` covers it
- Does it use LiteLLM? → `mlflow.litellm.autolog()`
- Does it have its own LLM client? → Check if there's a matching MLflow autolog for that client
- Does it support multiple providers with a factory pattern? → May need provider-specific routing (like CrewAI)

### 4. Report findings

Output a summary in this format:

```
## Autolog Support Report: <framework>

**Coverage level**: A / B / C
**Autolog module**: `mlflow.<framework>.autolog()` or "None"
**What autolog covers**: <list of span types captured>
**What autolog misses**: <list of gaps, or "Nothing — full coverage">
**LLM provider path**: <how the framework makes LLM calls>
**Recommended provider autolog**: `mlflow.<provider>.autolog()` or "Not needed — framework autolog covers LLM calls"
**Manual tracing needed for**: <list of things that need manual wrapping, or "Nothing">
```

This report will be used by the orchestrator to decide which tracing pattern to apply.

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
