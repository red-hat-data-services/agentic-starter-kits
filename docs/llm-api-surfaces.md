# LLM API Surfaces: Chat Completions vs Responses vs Messages

Red Hat OpenShift AI (RHOAI) 3.6 lets an agent talk to its model over the three LLM API surfaces used in this
repo: the
OpenAI **Chat Completions** API, the OpenAI **Responses** API, and the Anthropic **Messages** API. Every agent builder
has to pick one, and the choice shapes how you manage conversation state, invoke tools, stream output, and — most of
all — how portable your agent is across model servers.

This repo already contains working examples of all three surfaces. Instead of reverse-engineering the trade-offs from
kit source code, this guide compares the surfaces across four dimensions — **state management**, **tool-calling
model**, **streaming**, and **portability** — and points at the kit that demonstrates each choice in production-ready
form. It also covers how each surface interacts with MCP, MLflow tracing, and guardrails.

## Table of Contents

- [The Three Surfaces at a Glance](#the-three-surfaces-at-a-glance)
- [Quick Decision Guide](#quick-decision-guide)
- [Chat Completions](#chat-completions)
  - [State management](#state-management)
  - [Tool-calling model](#tool-calling-model)
  - [Streaming](#streaming)
  - [Portability](#portability)
  - [MCP tracing and guardrails](#mcp-tracing-and-guardrails)
- [OpenAI Responses API](#openai-responses-api)
  - [State management in Responses](#state-management-in-responses)
  - [Tool-calling model in Responses](#tool-calling-model-in-responses)
  - [Streaming in Responses](#streaming-in-responses)
  - [Portability in Responses](#portability-in-responses)
  - [MCP tracing and guardrails in Responses](#mcp-tracing-and-guardrails-in-responses)
- [Anthropic Messages API](#anthropic-messages-api)
  - [State management in Messages](#state-management-in-messages)
  - [Tool-calling model in Messages](#tool-calling-model-in-messages)
  - [Streaming in Messages](#streaming-in-messages)
  - [Portability in Messages](#portability-in-messages)
  - [MCP tracing and guardrails in Messages](#mcp-tracing-and-guardrails-in-messages)
- [Kit Example Matrix](#kit-example-matrix)
- [Cross-Cutting Notes](#cross-cutting-notes)
  - [Agent SSE is not LLM streaming](#agent-sse-is-not-llm-streaming)
  - [Where the surfaces meet](#where-the-surfaces-meet)
  - [Consuming vs exposing MCP](#consuming-vs-exposing-mcp)
- [References](#references)

## The Three Surfaces at a Glance

| Dimension | Chat Completions | Responses | Messages |
|---|---|---|---|
| Endpoint | `POST /v1/chat/completions` | `POST /v1/responses` | `POST /v1/messages` |
| Conversation state | Stateless — client resends full history each turn | Server-side state optional via `previous_response_id`; stateless use also supported | Stateless — client resends full history each turn |
| System prompt | A `system` message in the `messages` array | A top-level `instructions` field | A top-level `system` parameter |
| Tool calling | `tools` array; model returns `tool_calls`; results posted back as `role: "tool"` messages | Item-based — function calls and outputs are typed items in the `input`/`output` arrays | Content blocks — `tool_use` blocks from the model, `tool_result` blocks from the client |
| Streaming | SSE `chat.completion.chunk` deltas | SSE typed events (`response.output_text.delta`, ...) | SSE typed events (`content_block_delta`, ...) |
| Served by | vLLM, OGX, llm-d, Ollama — effectively everyone | OpenAI; recent vLLM releases ([compatibility](#portability-in-responses)); llm-d with a compatible backend | Anthropic; vLLM (native `/v1/messages` in recent releases, RHOAI image 0.13.0+); OGX (passthrough or translation) |
| Framework support in this repo | All of them — LangChain, CrewAI, LlamaIndex, AutoGen, ADK | Raw OpenAI SDK only | Claude Code binary only |
| Kit examples | 10 standard kits (LangGraph, CrewAI, LlamaIndex, ADK, AutoGen) | [vanilla_python](#openai-responses-api), [codex](#openai-responses-api) | [claude-code](#anthropic-messages-api) |

## Quick Decision Guide

- **Default to Chat Completions.** It is the de facto industry standard: every model server and every agent framework
  in this repo speaks it, and tool-calling works on all mainstream open-source models. If you have no reason to pick
  otherwise, pick this — start from [agents/langgraph/templates/react_agent](../agents/langgraph/templates/react_agent/README.md).
- **Pick Responses** when your endpoint serves `/v1/responses`, you want a structured item-based protocol, or you
  are embedding a client that requires it (Codex CLI does — see
  [agents/codex](../agents/codex/README.md)). Basic Responses support and Codex compatibility have different
  requirements — see [Portability in Responses](#portability-in-responses). Budget for a Chat Completions fallback
  if your endpoint may not serve
  `/v1/responses` — [vanilla_python](../agents/vanilla_python/templates/openai_responses_agent/README.md) shows the
  pattern (mind its blanket-404 caveat in [Portability in Responses](#portability-in-responses)).
- **Pick Messages** when you are running Claude Code or another Anthropic-native client, or your model server serves
  `/v1/messages` natively — see [agents/claude-code](../agents/claude-code/README.md).

## Chat Completions

The OpenAI Chat Completions API is the lingua franca of LLM serving. Ten of the standard kits in this repo use it —
every LangGraph template and example, CrewAI, LlamaIndex, Google ADK, and AutoGen — each through a different client
library that all end up at the same `POST /v1/chat/completions` endpoint.

### State management

The API is **stateless**: the server keeps no conversation memory, and the client sends the full `messages` array on
every turn:

```json
{
  "model": "qwen2-5-7b-instruct",
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "What is the weather in Boston?" },
    { "role": "assistant", "content": null, "tool_calls": [
      { "id": "call_1", "type": "function", "function": { "name": "get_weather", "arguments": "{ \"location\": \"Boston\" }" } }
    ] },
    { "role": "tool", "tool_call_id": "call_1", "content": "{\"temp_f\": 58}" }
  ]
}
```

The `tool_call_id` on each tool result must match the `id` of the assistant's tool call it answers —
schema-enforcing servers reject the request otherwise.

Conversation state is therefore the agent's responsibility. That is a feature for agents: LangGraph checkpoints state
in its graph, and [react_with_database_memory](../agents/langgraph/templates/react_with_database_memory/README.md)
persists it to a database. Agent checkpointing can also coexist with server-side conversation history; the agent
still needs to checkpoint its orchestration state and any response IDs it uses.

### Tool-calling model

**Native function calling.** You declare tools as JSON Schemas in the `tools` parameter, the model returns
`tool_calls` in its response, you execute and post results back as `role: "tool"` messages. All major open-source
tool-calling models support this; on vLLM it requires `--enable-auto-tool-choice --tool-call-parser <parser>`.

Most Chat Completions kits in this repo use native tool calling — e.g. the LangGraph
[react_agent](../agents/langgraph/templates/react_agent/src/react_agent/agent.py) binds tools with
`create_agent(model=chat, tools=tools)` and LangChain handles the `tool_calls` round-trip. Two qualifications:
[vanilla_python](../agents/vanilla_python/templates/openai_responses_agent/README.md) uses prompt-based
ReAct tool calling (`Action:`/`Observation:` parsing) by design — see [Responses](#openai-responses-api) for why —
and [crewai](../agents/crewai/templates/websearch_agent/README.md)'s mode is model-dependent: with its default local
Ollama model, litellm reports no function-calling support and CrewAI falls back to its own prompt-based ReAct loop,
so native `tool_calls` there require a function-calling-capable model.

### Streaming

`stream: true` returns SSE chunks (`chat.completion.chunk`) with incremental `delta` content. Six of the ten standard
kits token-stream their LLM calls and re-emit them as their own SSE response on `POST /chat/completions` — for
example, [crewai's `_handle_stream`](../agents/crewai/templates/websearch_agent/main.py) constructs the crew with
`stream=True` (`AssistanceAgents(llm=llm, stream=True).crew()`), iterates the `crew.kickoff_async(inputs=inputs)`
result, and forwards tokens to the client. The other four still serve agent-level SSE, but their LLM calls are not
token-streamed: the [guardrailed_agent](../agents/langgraph/examples/guardrailed_agent/README.md) sets
`disable_streaming=True` (NeMo Guardrails accepts tools only on non-streaming calls),
[human_in_the_loop](../agents/langgraph/templates/human_in_the_loop/README.md) uses `stream_mode="updates"` (complete
node outputs, not tokens), [llamaindex](../agents/llamaindex/templates/websearch_agent/README.md) awaits a
non-streaming `achat_with_tools` and emits the final answer as one chunk, and
[google adk](../agents/google/templates/adk/README.md) runs `runner.run_async` without a streaming `RunConfig` (see
[Agent SSE is not LLM streaming](#agent-sse-is-not-llm-streaming)).

### Portability

This is where Chat Completions wins outright. In this repo alone it is spoken by:

- **Model servers**: vLLM, OGX, llm-d, and Ollama (see [local-development.md](local-development.md) and
  [llm-d-deployment.md](llm-d-deployment.md))
- **Client libraries**: `langchain-openai` (LangGraph kits), CrewAI `LLM` via litellm, LlamaIndex `OpenAILike`,
  AutoGen `OpenAIChatCompletionClient`, Google ADK `LiteLlm`
- **Config-level consumers**: OpenClaw, OpenCode, and Langflow all point at an OpenAI-compatible endpoint

Switching `BASE_URL` from Ollama to OGX to llm-d to OpenAI requires no code change — just `.env` values.

### MCP tracing and guardrails

- **MCP**: consuming MCP servers works naturally — the
  [AutoGen MCP agent](../agents/autogen/templates/mcp_agent/README.md) loads tools from an MCP server at startup and
  presents them to the model as ordinary native tools over Chat Completions.
- **MLflow tracing**: the best coverage of the three surfaces. The framework autolog integrations in
  [tracing.md](../tracing.md) (`mlflow.langchain`, `mlflow.crewai`, `mlflow.llama_index`, `mlflow.litellm`) capture
  Chat Completions LLM calls, tools, and orchestration. The AutoGen kit additionally uses `mlflow.autogen` autolog,
  documented in its own [README](../agents/autogen/templates/mcp_agent/README.md) — note it disables streaming when
  tracing is enabled, because `mlflow.autogen.autolog()` does not support AutoGen's streaming APIs.
- **Guardrails**: the [guardrailed_agent](../agents/langgraph/examples/guardrailed_agent/README.md) wraps ChatOpenAI in
  NeMo Guardrails. NeMo's LLM adapter ecosystem is Chat-Completions-first, so this is the surface with the most mature
  guardrails story. Note the caveat: guardrails accept tools only on non-streaming LLM calls, so the kit sets
  `disable_streaming=True` on the LLM while still serving SSE to its own clients (see the explanation in the kit's
  [agent.py](../agents/langgraph/examples/guardrailed_agent/src/guardrailed_agent/agent.py)).

## OpenAI Responses API

The Responses API is OpenAI's newer surface, designed for reasoning models and agentic workloads. Two kits use it:
[vanilla_python](../agents/vanilla_python/templates/openai_responses_agent/README.md) as its primary surface with an
automatic fallback, and [codex](../agents/codex/README.md) as its exclusive surface.

### State management in Responses

Requests carry a top-level `instructions` field (the system prompt) plus an `input` array of typed items. The API can
also hold conversation state **server-side**: pass `previous_response_id` and the server stitches the conversation
together, so the client does not resend history. **Top-level `instructions` are not carried forward** by
`previous_response_id`: resend any required instructions on every request, including tool-result continuations
(see the [OpenAI migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses)).

The repo's example uses it statelessly —
[vanilla_python's `_messages_to_responses_input()`](../agents/vanilla_python/templates/openai_responses_agent/src/openai_responses_agent/agent.py)
converts chat-style messages into `instructions` plus `input_text`/`output_text` items and resends them each turn.
This keeps conversation history under the agent's control and works with model servers that do not retain
responses. Agents can also checkpoint their own state and response IDs while the server retains conversation
history; choose based on the backend's storage support and your recovery requirements.

### Tool-calling model in Responses

Tool calls are **typed items** in the input/output arrays rather than fields on a message — stricter and more
structured than `tool_calls`. Reasoning models also emit reasoning items that are expected to be fed back for
multi-turn tool use.

Two things to know from this repo:

- The same vLLM flags apply (`--enable-auto-tool-choice --tool-call-parser`), but **model choice is narrower**:
  Codex sends `namespace` tool types, which harmony models (gpt-oss / `GptOssForCausalLM`) do not support — see
  [Codex's Responses API Compatibility](../agents/codex/README.md#responses-api-compatibility) for tested
  model/parser combinations (e.g. Qwen3-Coder with `qwen3_coder`).
- [vanilla_python](../agents/vanilla_python/templates/openai_responses_agent/README.md) deliberately does **not** use
  native tool calling — it embeds tool source code in the system prompt and parses `Action:` lines with a regex. That
  keeps the example framework-free, at the cost of a hand-rolled ReAct loop. It is the only kit that never uses
  native tool calling regardless of model.

### Streaming in Responses

The API streams SSE typed events (`response.output_text.delta` and friends) rather than generic chunks. Note that
[vanilla_python](../agents/vanilla_python/templates/openai_responses_agent/main.py) does not token-stream the LLM: its
SSE response carries tool events and the final answer. No kit in this repo token-streams over Responses. The
frameworks can, though — for example the `langchain-openai` client the LangGraph kits pin supports
`ChatOpenAI(use_responses_api=True)` with streaming — so building a token-streaming Responses agent means using that
flag (or the raw SDK's `stream=True`) rather than writing a streaming layer from scratch.

### Portability in Responses

This is the weakest dimension. Support is OpenAI-first:

- **Served by**: OpenAI; recent vLLM releases; llm-d with a backend that serves Responses (see
  [llm-d-deployment.md](llm-d-deployment.md)). OGX can front it. Basic generation and native function calling were
  verified on RHOAI 3.6's vLLM `0.24.0+rhaiv.16`; v0.6.4 returned 404. Support depends on the backend build.
  The repo's **Codex setup has additional compatibility requirements**: upstream vLLM v0.25.1+,
  support for `developer` messages and namespace tools, and the correct model/parser combination — see
  [Codex compatibility](../agents/codex/README.md#responses-api-compatibility).
- **Framework clients**: no kit in this repo uses a framework client on the Responses surface — the frameworks
  themselves do support it (e.g. `langchain-openai`'s `ChatOpenAI(use_responses_api=True)`), but the repo's example
  uses the raw `openai` Python SDK, which is the practical answer for framework-free agents.

Because an arbitrary OpenAI-compatible endpoint may not serve `/v1/responses`, vanilla_python implements a **runtime
fallback**: a 404 from `responses.create` permanently flips the agent to `chat.completions.create`; a 400 falls back
for that call only (a 400 may be a legitimate request error, so the result is not cached). The behavior is covered by
[tests](../agents/vanilla_python/templates/openai_responses_agent/tests/test_agent.py) — if you pick Responses for an
agent that must run against unknown endpoints, copy this pattern. One caveat before copying it verbatim: the example
treats **any** 404 as a missing endpoint, and servers also return 404 for an unknown model — a typo'd model name
permanently flips the agent to Chat Completions even though `/v1/responses` works. If that distinction matters, probe
the endpoint explicitly instead of keying off the status code alone.

### MCP tracing and guardrails in Responses

- **MCP**: [codex](../agents/codex/README.md#mcp-servers) consumes MCP servers configured via TOML/JSON at startup —
  MCP consumption is independent of the LLM surface (see
  [Consuming vs exposing MCP](#consuming-vs-exposing-mcp)).
- **MLflow tracing**: `mlflow.openai.autolog()` captures raw `responses.create()` calls — this is what
  [vanilla_python's tracing.py](../agents/vanilla_python/templates/openai_responses_agent/src/openai_responses_agent/tracing.py)
  uses (a Level C integration in [tracing.md](../tracing.md) terms: LLM autolog plus manual wrapping of tools and the
  agent entry point). Codex traces through a separate
  [`@mlflow/codex` hook overlay](../agents/codex/deployment/build-mlflow/mlflow-tracing.md) rather than the Python
  SDK.
- **Guardrails**: no kit in this repo combines guardrails with Responses. NeMo Guardrails' LLM adapters target Chat
  Completions, so expect custom integration work if you need rails on this surface.

## Anthropic Messages API

The Messages API is Anthropic's surface. The repo's example is [claude-code](../agents/claude-code/README.md), which
runs the Claude Code binary against four backends: Anthropic API, Google Vertex AI, vLLM direct, and vLLM via the OGX
gateway.

### State management in Messages

Like Chat Completions, the API is **stateless** — the client resends the full `messages` array each turn. The system
prompt is a top-level `system` parameter rather than a message, and message content is an array of typed blocks
(text, `tool_use`, `tool_result`, ...) rather than a plain string.

Claude Code's own system prompt is very large (~23K tokens), so
[claude-code's vLLM guide](../agents/claude-code/vllm/README.md) requires models with at least 32K context and
recommends 128K+ — context-window budgeting matters more on this kit than any other in the repo.

### Tool-calling model in Messages

**Native tool calling via content blocks**: the model emits `tool_use` blocks, and the client replies with `tool_result`
blocks in the next turn. Claude Code's file and shell tools run over this protocol. It is functionally equivalent to
Chat Completions tool calling — the difference is shape (blocks vs `tool_calls` fields), not capability.

### Streaming in Messages

`stream: true` produces typed SSE events (`message_start`, `content_block_delta`, `message_delta`, ...). Both
streaming and non-streaming `/v1/messages` are exercised by
[claude-code's vLLM endpoint tests](../agents/claude-code/vllm/tests/test_vllm_endpoints.sh). Like codex, this kit is
an interactive CLI agent (used via `oc exec`), so it has no `POST /chat/completions` of its own.

### Portability in Messages

Support is Anthropic-first but improving:

- **Anthropic API and Vertex AI** directly, via the Claude Code backends in
  [claude-code](../agents/claude-code/README.md).
- **vLLM** can serve `/v1/messages` natively in recent releases (the RHOAI vLLM `0.13.0` image does; older
  versions such as v0.6.x return 404 there) — see
  [agents/claude-code/vllm](../agents/claude-code/vllm/README.md).
- **OGX** fronts Anthropic-native traffic with a twist worth knowing: it serves `/v1/messages` in two modes,
  set by its provider type. With `remote::openai` it **translates Anthropic requests into OpenAI Chat
  Completions format**, so the backend can be any vLLM; with `remote::vllm` it passes through to the backend's
  native `/v1/messages` (and fails if the backend lacks it — there is no automatic fallback) — see
  [agents/claude-code/ogx](../agents/claude-code/ogx/README.md). Your agent speaks Messages; the wire behind the
  gateway may not be. The tested translation provider rejects extended thinking and does not implement token
  counting; use native passthrough with a backend that supports those features when needed.

### MCP tracing and guardrails in Messages

- **MCP**: the claude-code kit wires MCP servers through `MCP_CONFIG_FILE`/`MCP_CONFIG_JSON` — the entrypoint's
  `setup_mcp` passes them to Claude Code's `--mcp-config` flag (see "MCP Server Configuration" in
  [agents/claude-code/README.md](../agents/claude-code/README.md)). For more MCP consumption examples, see
  [autogen](../agents/autogen/templates/mcp_agent/README.md) (Chat Completions) and
  [codex](../agents/codex/README.md#mcp-servers) (Responses) — the surface does not change the MCP client code.
- **MLflow tracing**: kit-level tracing exists via `mlflow autolog claude` — the entrypoint configures it
  automatically when `MLFLOW_TRACKING_URI` is set (see "MLflow Tracing (Optional)" in
  [agents/claude-code/README.md](../agents/claude-code/README.md)). It is the same hook pattern the codex kit uses
  with [`@mlflow/codex`](../agents/codex/deployment/build-mlflow/mlflow-tracing.md), rather than the Python SDK
  pattern the standard kits use.
- **Guardrails**: no kit example. As with Responses, expect custom integration work.

## Kit Example Matrix

| Kit | Surface | LLM client | MCP | MLflow | Agent SSE | Tool calling |
| --- | --- | --- | --- | --- | --- | --- |
| [langgraph/react_agent](../agents/langgraph/templates/react_agent/README.md) | Chat Completions | `langchain-openai` | — | autolog | yes | native |
| [langgraph/agentic_rag](../agents/langgraph/templates/agentic_rag/README.md) | Chat Completions | `langchain-openai` | — | autolog | yes | native |
| [langgraph/human_in_the_loop](../agents/langgraph/templates/human_in_the_loop/README.md) | Chat Completions | `langchain-openai` | — | autolog | yes | native |
| [langgraph/react_with_database_memory](../agents/langgraph/templates/react_with_database_memory/README.md) | Chat Completions | `langchain-openai` | — | autolog | yes | native |
| [langgraph/ci_failure_summarizer](../agents/langgraph/examples/ci_failure_summarizer/README.md) | Chat Completions | `langchain-openai` | — | autolog | yes | native |
| [langgraph/guardrailed_agent](../agents/langgraph/examples/guardrailed_agent/README.md) | Chat Completions | `langchain-openai` via NeMo Guardrails | — | autolog | yes (LLM calls non-streaming) | native |
| [crewai/websearch_agent](../agents/crewai/templates/websearch_agent/README.md) | Chat Completions | CrewAI `LLM` (litellm) | — | autolog | yes | model-dependent (native with function-calling models, ReAct otherwise) |
| [llamaindex/websearch_agent](../agents/llamaindex/templates/websearch_agent/README.md) | Chat Completions | LlamaIndex `OpenAILike` | — | autolog | yes | native |
| [google/adk](../agents/google/templates/adk/README.md) | Chat Completions | ADK `LiteLlm` (litellm) | — | autolog (litellm) | yes | native |
| [autogen/mcp_agent](../agents/autogen/templates/mcp_agent/README.md) | Chat Completions | AutoGen `OpenAIChatCompletionClient` | consumes | autolog | yes (`+mcp.tool_usage`; token streaming defaults off when MLflow tracing is on) | native (MCP tools) |
| [a2a/langgraph_crewai_agent](../agents/a2a/templates/langgraph_crewai_agent/README.md) | Chat Completions | `langchain-openai` + CrewAI `LLM` | — | autolog | A2A protocol | native |
| [vanilla_python/openai_responses_agent](../agents/vanilla_python/templates/openai_responses_agent/README.md) | Responses (+ Chat Completions fallback) | `openai` SDK | — | autolog (Level C) | tool events + final answer (not token-streamed) | prompt-based ReAct |
| [codex](../agents/codex/README.md) | Responses (exclusive) | Codex CLI binary | consumes | `@mlflow/codex` hook | — (CLI) | native (namespace tools) |
| [claude-code](../agents/claude-code/README.md) | Messages | Claude Code binary | config (`MCP_CONFIG_FILE`/`MCP_CONFIG_JSON`) | `mlflow autolog claude` hook | — (CLI) | native |
| [openclaw](../agents/openclaw/deployment/README.md) | Chat Completions (config) | OpenClaw image | — | OTel overlay | — (web UI) | native (required) |
| [opencode](../agents/opencode/README.md) | Chat Completions (config) | `@ai-sdk/openai-compatible` | consumes | overlay | — (CLI) | native |
| [langflow/simple_tool_calling_agent](../agents/langflow/templates/simple_tool_calling_agent/README.md) | Chat Completions (config) | Langflow components | — | Langfuse instead | — (Langflow API) | native |

## Cross-Cutting Notes

### Agent SSE is not LLM streaming

Two distinct streaming decisions get conflated easily:

1. **How your agent streams to its clients.** Every standard kit serves SSE on `POST /chat/completions` regardless of
   the LLM surface underneath.
2. **How your agent's LLM calls stream.** Token streaming from the model server.

The guardrailed agent disables LLM streaming (NeMo Guardrails accepts tools only on non-streaming calls) while still
serving SSE to its clients; vanilla_python streams tool events and the final answer, but not LLM tokens; and the
autogen MCP agent defaults token streaming off when `MLFLOW_TRACKING_URI` is set (`mlflow.autogen.autolog()` does not
support streaming) — its SSE endpoint keeps serving, but responses arrive as complete chunks and its playground cannot
display them live. These are all legitimate points in the design space — decide each independently.

### Where the surfaces meet

Two places in this repo show the surfaces interoperating rather than competing:

- **OGX translation for Claude Code**: your agent speaks Messages; with OGX's `remote::openai` provider,
  requests are translated to Chat Completions for any vLLM backend, including ones without native
  `/v1/messages` ([agents/claude-code/ogx](../agents/claude-code/ogx/README.md)).
- **vanilla_python's fallback**: one agent, two surfaces, negotiated per endpoint at runtime
  ([agent.py](../agents/vanilla_python/templates/openai_responses_agent/src/openai_responses_agent/agent.py)).

Both are reminders that the surface your agent speaks and the surface your inference stack serves can differ —
gateways and fallbacks bridge the gap, at the cost of translation fidelity.

### Consuming vs exposing MCP

The Model Context Protocol is **orthogonal to the LLM API surface** — an MCP client runs in your agent's process and
presents tools to the model however the LLM surface formats them:

- **Consuming MCP servers**: [autogen/mcp_agent](../agents/autogen/templates/mcp_agent/README.md) loads tools from an
  MCP server over SSE and registers them as native tools (Chat Completions);
  [codex](../agents/codex/README.md#mcp-servers) and [opencode](../agents/opencode/README.md) configure MCP servers
  at startup (Responses and Chat Completions respectively). The MCP client code does not change with the surface.
- **Exposing an MCP server**: [mcp_automl_template](../agents/autogen/templates/mcp_agent/mcp_automl_template/README.md)
  packages AutoML tools as an MCP server that other agents consume. Note that the standard kits in this repo expose
  themselves via the OpenAI-compatible `POST /chat/completions` contract (or A2A), not via MCP — choosing your agent's
  own API surface is a separate decision from choosing the LLM surface it consumes.

## References

- [OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat)
- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [tracing.md](../tracing.md) — MLflow tracing architecture and autolog levels
- [guardrails.md](guardrails.md) — NeMo Guardrails integration
- [llm-d-deployment.md](llm-d-deployment.md) — llm-d inference routing on OpenShift AI
- [local-development.md](local-development.md) — local model serving with Ollama and OGX
