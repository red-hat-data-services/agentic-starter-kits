# Code Quality Evaluation Framework for Coding Agents on RHOAI

This document surveys existing benchmarks for evaluating coding agents, recommends which to adopt, and proposes an evaluation matrix for measuring quality across agent deployments on RHOAI.

The existing evaluation infrastructure in `evals/` covers framework agents (CrewAI, LangGraph) that expose `/chat/completions` HTTP endpoints. Coding agents (OpenClaw, Claude Code, OpenCode) are CLI-based and require a different integration approach — the existing `evals/harness/runner.py` cannot drive them directly. The scorer framework in `evals/harness/scorers/` is reusable, but the runner and benchmark harness need to be purpose-built for coding agent evaluation.

**Core question:** What is the quality delta when running a coding agent on RHOAI (self-hosted via vLLM/OGX) vs. the same agent on its premium subscription?

## Benchmark Selection

### Survey

| Benchmark | Agentic? | Tasks | Runtime-agnostic? | Fit |
|---|---|---|---|---|
| **Terminal-Bench v2.0** | Yes -- full terminal, multi-step, tool use, Docker sandboxes | 89 | Yes -- container-installed, Python BaseAgent, or MCP server | **Primary** |
| **SWE-bench Verified** | Yes -- real GitHub issues, repo nav, file editing | 500 | Yes -- agent submits patches, harness runs tests | **Secondary** (see contamination caveat) |
| **Aider Polyglot** | Semi -- 2 attempts with test feedback, 6 languages | 225 | Aider-native but adaptable | Supplementary |
| **BigCodeBench** | No -- function-level, library usage | 1,140 | Model-only | Out of scope |
| **HumanEval / MBPP** | No -- single-turn completion | 164 / 974 | Model-only | Out of scope (saturated) |
| **LiveCodeBench** | No -- competitive programming | ~1,055 (v6, continuously growing) | Model-only | Out of scope |

### Recommendation: Terminal-Bench as primary, SWE-bench Verified as secondary

**Why Terminal-Bench:**

- Tests the exact dimensions we care about: multi-turn tool use, file editing, terminal interaction, real-world tasks (compile, debug, deploy)
- Runtime-decoupled by design: supports multiple integration modes (AbstractInstalledAgent, BaseAgent, MCPAgent) which can be adapted for pod-deployed agents
- 89 tasks is right-sized for repeated evaluation across multiple matrix cells (vs. SWE-bench's 500 which is expensive per run)
- Categories span our customer use cases: coding, sysadmin, data science, security

**Why SWE-bench Verified as secondary:**

- Industry gold standard -- customers and analysts know it
- Tests a different dimension (bug fix / feature implementation in real repos) vs. Terminal-Bench (task completion in terminal)
- Heavier to run but valuable for headline numbers
- K8s-native harness exists (Inspect Evals supports `sandbox_type: k8s`)

**Contamination caveat:** SWE-bench Verified has known contamination concerns — models have been observed reproducing gold-patch solutions verbatim, and OpenAI stopped reporting Verified scores in early 2026. SWE-bench Pro (1,865 tasks, multi-language, proprietary codebases) was created to address this. If contamination undermines Verified's value for our comparisons, Pro is the replacement. For our use case (comparing the *same model* across different backends), contamination is less of a concern since it affects all cells equally — but for cross-model comparisons (Tier 2), Pro may be necessary.

**kbench** (shareAI-lab/kbench) wraps both Terminal-Bench and SWE-bench with built-in harnesses for Claude Code, Codex, and Gemini CLI plus a `custom-adapter` mode. Worth evaluating as the orchestration layer.

## Evaluation Matrix

### Axes

| Axis | Values |
|---|---|
| **Agents** | OpenClaw (deployed), Claude Code (in progress), OpenCode (planned -- RHAIRFE-2323) |
| **Inference backends** | Premium API (Anthropic / OpenAI), vLLM direct, OGX -> vLLM |
| **Models** | Frontier (latest Sonnet, latest GPT) for premium API controls. Self-hosted: Qwen/Qwen3.6-27B, nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4, google/gemma-4-31B-it, openai/gpt-oss-120b, mistralai/Mistral-Small-4-119B-2603. Pin exact model revisions at eval time. |
| **Benchmark** | Terminal-Bench v2.0 (primary) |

### Priority Cells

Not every cell matters equally. The high-value comparisons are:

**Tier 1 -- Quality delta (same agent, different backend):**

| Agent | Premium API | vLLM direct | OGX -> vLLM | What it tells us |
|---|---|---|---|---|
| OpenClaw (deployed) | latest GPT (OpenAI) | gpt-oss-120b | gpt-oss-120b via OGX | Baseline — open agent, established pattern |
| Claude Code (in progress) | latest Sonnet (Anthropic) | gpt-oss-120b | gpt-oss-120b via OGX | Model capability gap + OGX translation fidelity |
| OpenCode (planned) | latest GPT (OpenAI) | gpt-oss-120b | gpt-oss-120b via OGX | Same, once deployed (RHAIRFE-2323) |

These 9 cells answer the core question: "how much quality do I lose going self-hosted?"

**Tier 2 -- Model scaling (same backend, different model sizes):**

| Agent | gpt-oss-20b | gpt-oss-120b | Llama 3.3 70B |
|---|---|---|---|
| OpenClaw | x | x | x |

These cells answer: "which self-hosted model gives acceptable quality?"

**Tier 3 -- Cross-agent comparison (same model, different agents):**

Run all 3 agents against the same model/backend to compare agent quality independent of model. Lower priority since agents have different strengths.

### What to skip

- Codex + Gemini CLI: defer until their deployment RFEs are further along
- Local inference (Ollama): out of scope for RHOAI validation
- HumanEval/MBPP: saturated, doesn't test agentic capabilities

## Metrics

Beyond pass rate:

| Metric | Why it matters |
|---|---|
| **Task pass rate** | Headline number -- % of tasks solved |
| **Token efficiency** | Does self-hosted use more tokens for the same task? Directly impacts cost. |
| **Latency (TTFT + total)** | User experience on self-hosted vs. premium |
| **Tool call count** | More tool calls = less efficient reasoning. Signals model capability gap. |
| **Failure mode analysis** | Classify each failed task by failure mode (e.g., tool_misuse, repeated_error_loop, hallucinated_completion, excessive_steps, verification_skipped). Report distribution per matrix cell to identify whether quality drops are model-capability failures vs. translation-layer failures. These failure mode scorers do not exist yet and need to be built — the `evals/harness/scorers/` framework provides the extension point. |
| **Pass rate by category** | Terminal-Bench categories: coding, sysadmin, data science, security -- where does quality drop? |

The existing scorer framework in `evals/harness/scorers/` (tool_sequence, plan_coherence, safety, latency) is reusable for coding agent evaluation. Token usage capture depends on the agent's response including a `usage` field or MLflow tracing being configured for backfill — it is not guaranteed for all agents.

## Quality Attribution

A quality drop on RHOAI could come from three sources. The control experiment design:

| Source | How to isolate | Control experiment |
|---|---|---|
| **Model capability** | Same agent, frontier model vs. self-hosted model, both via direct API | Claude Code + claude-sonnet vs. Claude Code + gpt-oss-120b (both direct, no OGX) |
| **Inference translation** | Same agent, same model, with vs. without OGX | Claude Code + gpt-oss-120b (vLLM direct) vs. Claude Code + gpt-oss-120b (OGX -> vLLM) |
| **Platform issues** | Same agent, same model, local vs. on-cluster | Claude Code + gpt-oss-120b (local Docker) vs. Claude Code + gpt-oss-120b (OpenShift pod) |

If quality is the same through OGX as through direct vLLM, the translation layer is clean. If it drops, inspect OGX request/response logs for tool-call schema differences.

## Running Against Pod-Deployed Agents

Terminal-Bench natively supports three agent integration modes: `AbstractInstalledAgent` (agent installed in the benchmark container), `BaseAgent` (Python API), and `MCPAgent` (MCP protocol over network). For RHOAI pod-deployed agents, we adapt these:

**Option A: MCPAgent mode (recommended for CI)**

Terminal-Bench exposes tmux session tools via MCP. The agent connects to these tools regardless of where it runs. For a pod-deployed agent, the MCP connection goes over the network -- cleanest separation. This uses Terminal-Bench's native MCPAgent mode.

**Option B: `oc exec` adapter (RHOAI-specific)**

Write a thin adapter that extends Terminal-Bench's `AbstractInstalledAgent` interface, where `_run_agent_commands()` does `oc exec` into the agent pod. This is not a built-in Terminal-Bench mode — it's an RHOAI-specific strategy. Works but tightly couples the harness to OpenShift.

**Option C: In-pod execution**

Install Terminal-Bench inside the agent pod and run via `AbstractInstalledAgent` directly. Simplest but burns cluster resources and doesn't test the "deployed service" pattern.

Recommendation: Start with Option C for the initial evaluation (fastest to validate), move to Option A for ongoing CI.

## Proposed First Run

**Scope:** Start with deployed agents (OpenClaw, Claude Code) x 3 backends x Terminal-Bench v2.0 (89 tasks). Add OpenCode once deployed (RHAIRFE-2323).

**Prerequisites:**

- Terminal-Bench v2.0 installed (pip install) -- pin exact version at eval start
- Agent pods deployed on RHOAI (OpenClaw deployed, Claude Code in progress, OpenCode planned -- RHAIRFE-2323)
- vLLM serving gpt-oss-120b (already running)
- OGX deployed and routing (already running)
- Premium API keys for control runs
- Baseline stability check: run premium API controls 3x to establish variance before claiming quality deltas

**Timeline estimate:** ~1 sprint to run Tier 1 cells and produce the quality delta report.

**Deliverable:** Quality delta report with pass rates, token efficiency, and failure mode analysis across the 9 Tier 1 cells. Recommendation on which self-hosted configuration delivers acceptable quality for customers.

## Reproducibility Requirements

These are mandatory for valid cross-cell and longitudinal comparisons:

- **Benchmark version pinning:** Pin Terminal-Bench to an exact version (e.g., `terminal-bench==2.0.3`) at the start of each evaluation cycle. Document the version in every results report.
- **Model revision pinning:** Record exact model identifiers (HuggingFace revision hash or API model version string) for every cell. Self-hosted models: record the vLLM `--model` path and revision. Premium APIs: record the model string returned in the API response.
- **Repeat-run variance policy:** Run each cell a minimum of 3 times. Report mean and standard deviation. A quality delta claim requires the delta to exceed 2x the observed standard deviation.
- **Baseline stability check:** Before claiming any quality delta, run premium API controls 3x to establish variance. If premium API variance exceeds 5% pass rate across runs, investigate before proceeding.

## Open Questions

1. **GPU budget for evaluation runs?** Full Tier 1 matrix with gpt-oss-120b requires significant inference compute. Need allocation confirmed before starting.
2. **kbench as orchestrator?** kbench wraps both Terminal-Bench and SWE-bench with built-in agent adapters — run a quick spike to evaluate whether it saves us from building our own harness.
3. **SWE-bench Pro vs. Verified:** If contamination concerns invalidate Verified for cross-model comparisons (Tier 2), evaluate SWE-bench Pro as replacement.
