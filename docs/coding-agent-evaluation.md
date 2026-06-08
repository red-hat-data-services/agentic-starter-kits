# Code Quality Evaluation Framework for Coding Agents on RHOAI

This document surveys existing benchmarks for evaluating coding agents, recommends which to adopt, and proposes an evaluation matrix for measuring quality across agent deployments on RHOAI. It extends the existing evaluation infrastructure in `evals/` (which covers framework agents like CrewAI and LangGraph) to coding-specific agents (OpenClaw, Claude Code, OpenCode).

**Core question:** What is the quality delta when running a coding agent on RHOAI (self-hosted via vLLM/OGX) vs. the same agent on its premium subscription?

## Benchmark Selection

### Survey

| Benchmark | Agentic? | Tasks | Runtime-agnostic? | Fit |
|---|---|---|---|---|
| **Terminal-Bench v2.0** | Yes -- full terminal, multi-step, tool use, Docker sandboxes | 89 | Yes -- container-installed, Python BaseAgent, or MCP server | **Primary** |
| **SWE-bench Verified** | Yes -- real GitHub issues, repo nav, file editing | 500 | Yes -- agent submits patches, harness runs tests | **Secondary** |
| **Aider Polyglot** | Semi -- 2 attempts with test feedback, 6 languages | 225 | Aider-native but adaptable | Supplementary |
| **BigCodeBench** | No -- function-level, library usage | 1,140 | Model-only | Out of scope |
| **HumanEval / MBPP** | No -- single-turn completion | 164 / 974 | Model-only | Out of scope (saturated) |
| **LiveCodeBench** | No -- competitive programming | 1,055 | Model-only | Out of scope |

### Recommendation: Terminal-Bench as primary, SWE-bench Verified as secondary

**Why Terminal-Bench:**

- Tests the exact dimensions we care about: multi-turn tool use, file editing, terminal interaction, real-world tasks (compile, debug, deploy)
- Runtime-decoupled by design: supports 3 integration modes including MCP, which maps cleanly to pod-deployed agents via `oc exec`
- 89 tasks is right-sized for repeated evaluation across multiple matrix cells (vs. SWE-bench's 500 which is expensive per run)
- Categories span our customer use cases: coding, sysadmin, data science, security

**Why SWE-bench Verified as secondary:**

- Industry gold standard -- customers and analysts know it
- Tests a different dimension (bug fix / feature implementation in real repos) vs. Terminal-Bench (task completion in terminal)
- Heavier to run but valuable for headline numbers
- K8s-native harness exists (Inspect Evals supports `sandbox_type: kubernetes`)

**kbench** (shareAI-lab/kbench) wraps both Terminal-Bench and SWE-bench with built-in harnesses for Claude Code, Codex, and Gemini CLI plus a `custom-adapter` mode. Worth evaluating as the orchestration layer.

## Evaluation Matrix

### Axes

| Axis | Values |
|---|---|
| **Agents** | OpenClaw, Claude Code, OpenCode |
| **Inference backends** | Premium API (Anthropic / OpenAI), vLLM direct, OGX -> vLLM |
| **Models** | Frontier (claude-sonnet-4-5, gpt-5.4), Self-hosted (gpt-oss-20b, gpt-oss-120b, Llama 3.3 70B, Qwen 3.5) |
| **Benchmark** | Terminal-Bench v2.0 (primary) |

### Priority Cells

Not every cell matters equally. The high-value comparisons are:

**Tier 1 -- Quality delta (same agent, different backend):**

| Agent | Premium API | vLLM direct | OGX -> vLLM | What it tells us |
|---|---|---|---|---|
| Claude Code | claude-sonnet (Anthropic) | gpt-oss-120b | gpt-oss-120b via OGX | Model capability gap + OGX translation fidelity |
| OpenCode | gpt-5.4 (OpenAI) | gpt-oss-120b | gpt-oss-120b via OGX | Same, OpenAI path |
| OpenClaw | gpt-5.4 (OpenAI) | gpt-oss-120b | gpt-oss-120b via OGX | Same, open agent |

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
| **Failure mode analysis** | Classify each failed task using the AgentDev scorer taxonomy (tool_misuse, repeated_error_loop, hallucinated_completion, excessive_steps, verification_skipped, etc.). Report distribution per matrix cell to identify whether quality drops are model-capability failures vs. translation-layer failures. |
| **Pass rate by category** | Terminal-Bench categories: coding, sysadmin, data science, security -- where does quality drop? |

The existing evaluation harness in `evals/harness/` already captures latency, token usage, and tool calls per task. The `evals/harness/scorers/` framework provides the extension point for failure mode classification.

## Quality Attribution

A quality drop on RHOAI could come from three sources. The control experiment design:

| Source | How to isolate | Control experiment |
|---|---|---|
| **Model capability** | Same agent, frontier model vs. self-hosted model, both via direct API | Claude Code + claude-sonnet vs. Claude Code + gpt-oss-120b (both direct, no OGX) |
| **Inference translation** | Same agent, same model, with vs. without OGX | Claude Code + gpt-oss-120b (vLLM direct) vs. Claude Code + gpt-oss-120b (OGX -> vLLM) |
| **Platform issues** | Same agent, same model, local vs. on-cluster | Claude Code + gpt-oss-120b (local Docker) vs. Claude Code + gpt-oss-120b (OpenShift pod) |

If quality is the same through OGX as through direct vLLM, the translation layer is clean. If it drops, inspect OGX request/response logs for tool-call schema differences.

## Running Against Pod-Deployed Agents

Terminal-Bench supports 3 integration modes. For RHOAI:

**Option A: MCP server mode (recommended for CI)**

Terminal-Bench exposes tmux session tools via MCP. The agent connects to these tools regardless of where it runs. For a pod-deployed agent, the MCP connection goes over the network -- cleanest separation.

**Option B: `oc exec` adapter**

Write a thin adapter that implements Terminal-Bench's `AbstractInstalledAgent` interface, where `_run_agent_commands()` does `oc exec` into the agent pod. Works but tightly couples the harness to OpenShift.

**Option C: In-pod execution**

Install Terminal-Bench inside the agent pod and run directly. Simplest but burns cluster resources and doesn't test the "deployed service" pattern.

Recommendation: Start with Option C for the initial evaluation (fastest to validate), move to Option A for ongoing CI.

## Proposed First Run

**Scope:** 3 agents x 3 backends x Terminal-Bench v2.0 (89 tasks) = 9 evaluation runs (~800 task executions total)

**Prerequisites:**

- Terminal-Bench v2.0 installed (pip install)
- Agent pods deployed on RHOAI (OpenClaw done, Claude Code in progress, OpenCode next)
- vLLM serving gpt-oss-120b (already running)
- OGX deployed and routing (already running)
- Premium API keys for control runs

**Timeline estimate:** ~1 sprint to run Tier 1 cells and produce the quality delta report.

**Deliverable:** Quality delta report with pass rates, token efficiency, and failure mode analysis across the 9 Tier 1 cells. Recommendation on which self-hosted configuration delivers acceptable quality for customers.

## Open Questions

1. **Which Terminal-Bench version to pin?** v2.0 is current but the benchmark is actively evolving.
2. **GPU budget for evaluation runs?** 9 runs x 89 tasks with gpt-oss-120b requires significant inference compute.
3. **Baseline stability:** Do premium API results vary across runs? Need to establish variance before claiming a quality delta.
4. **kbench as orchestrator?** It wraps both benchmarks with built-in agent adapters -- worth a quick spike before building our own harness.
