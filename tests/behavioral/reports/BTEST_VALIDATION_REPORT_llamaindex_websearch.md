# Behavioral Test Validation Report: LlamaIndex Websearch Agent

**Ticket**: RHAIENG-4225
**Agent**: `agents/llamaindex/websearch_agent`
**Date**: 2026-05-26
**Cluster**: `agen-e2e-rhoai2`, namespace `adonheis-testing`
**Model**: `qwen2-5-7b-instruct` via vLLM

---

## Phase 11a: Pytest Behavioral Tests

**Status**: [PASS]

- 15/15 tests collected (13 fast + 2 slow)
- 13/13 non-slow tests pass
- 2/2 slow pass@k tests pass
- Run from repo root with `uv run --extra test`

## Phase 11b: MLflow Tool Enrichment Gate

**Status**: [PASS]

- `MLflowTraceClient.enrich_eval_result()` successfully extracts `tool_calls` from traces
- `score_tool_selection()` (F1 scorer) used for tool validation
- `score_hallucinated_tools()` confirmed no hallucinated tools
- No "MLflow enrichment failed" warnings emitted
- **Fix applied**: `mlflow_client.py` updated to extract actual tool name from span `attributes.name` — LlamaIndex autolog uses `FunctionTool.__call__` as span name but stores `dummy_web_search` in attributes

## Phase 11c: MLflow Trace Structure

**Status**: [PASS]

Span types confirmed:
- `[TOOL]` — `FunctionTool.__call__` / `FunctionTool.call` with `name: "dummy_web_search"`
- `[CHAT_MODEL]` — `OpenAILike.achat` with `model_name: "qwen2-5-7b-instruct"`
- `[CHAIN]` — `FunctionCallingAgent.run`, `.prepare_chat_history`, `.handle_llm_input`, `.handle_tool_calls`
- `[LLM]` — `OpenAILike._prepare_chat_with_tools`, `OpenAILike.achat`
- Parent/child nesting confirmed (not all ROOT)

## Phase 11d: Agent Pod Logs

**Status**: [PASS]

- `[Tracing Enabled] MLflow -> https://rh-ai.apps.rosa..., Experiment: adonheis-testing`
- All requests return 200 OK
- No MLflow connection errors or auth failures
- Only InsecureRequestWarning (expected for dev/test TLS)

## Phase 11e: EvalHub E2E Job

**Status**: [PASS]

LlamaIndex websearch agent job `cc591868-2cb9-4336-867f-c80ad382fb52` completed with:
- `tool_selection`: 1.0
- `hallucinated_tools`: 1.0
- `tool_call_validity`: 1.0
- `tool_sequence`: 1.0
- `mlflow_run_id`: `2a6f05f76106494a87e9c63c82bc72cf`

## Phase 11f: E2E MLflow Enrichment

**Status**: [PASS]

All 6 agents have non-null `mlflow_run_id`:
| Agent | mlflow_run_id |
|---|---|
| react_agent | 3085bbfd61e34902a3eae16858df3e35 |
| openai_responses | c01a232682bf44afb99d0ad5df9d639b |
| autogen_mcp | 082cf3d44b614d4aa02d7691c5684c8a |
| crewai_websearch | 8ac902a6f76044afb5fe47904ed1012a |
| agentic_rag | c55830aeac8e49fbbc2f6c8f4c42d195 |
| llamaindex_websearch | 2a6f05f76106494a87e9c63c82bc72cf |

## Phase 11g: E2E MLflow Trace Structure

**Status**: [PASS]

Post-E2E trace inspection confirmed CHAIN, LLM, CHAT_MODEL spans with proper parent/child nesting.

## Phase 11h: Agent Pod Logs After E2E

**Status**: [PASS]

Clean logs — all 200 OK, no errors, no tracing failures.

## Phase 11i: EvalHub Adapter Container

**Status**: [PASS]

- Fixture present: `fixtures/llamaindex_websearch/tool_use.yaml` (build-time assertion passed)
- Provider registered successfully
- Job completed with `state: completed`
- Scores non-null and reasonable (all 1.0)

## Phase 11j: Cross-Agent Consistency Check

**Status**: [PASS] (13/13 points)

One deviation found and fixed: vanilla_python had redundant `@pytest.mark.asyncio` decorators removed for consistency with all other agents.

## Phase 11k: Validation Report

**Status**: [PASS] — this document.

---

## MLflow Trace Summary

- LlamaIndex autolog produces different span names than LangGraph: `FunctionTool.__call__` vs `search`
- The actual tool name is in span `attributes.name`, not the span name itself
- Fix applied to `evals/harness/mlflow_client.py` to prefer `attributes.name` over `span.name` for TOOL spans
- Fix is backwards-compatible — falls back to `span.name` when `attributes.name` is absent

## EvalHub E2E Summary

- All 6 agents completed successfully
- All 6 have non-null `mlflow_run_id`
- LlamaIndex websearch agent scored 1.0 across all 4 metrics
- Adapter image built with new `fixtures/llamaindex_websearch/tool_use.yaml`

## Bugs Filed

None required — all tracing indicators present and working. The `mlflow_client.py` fix was applied as test infrastructure (in scope).
