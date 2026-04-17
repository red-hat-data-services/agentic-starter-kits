---
name: verify-traces
description: Verifies tracing works correctly after integration by running both code review and live trace testing.
argument-hint: "<agent_path>"
disable-model-invocation: true
---

# Verify Traces After Tracing Integration

> **Usage:** `/verify-traces <agent_path>`
> **Example:** `/verify-traces agents/autogen/chat_agent`

You are verifying that MLflow tracing works correctly after integrating it into a new agent template. This is the final validation step in the tracing integration workflow.

## Input

The agent path is: $ARGUMENTS

You also need the **coverage level** (A, B, or C). If not provided, determine it by reading the agent's `tracing.py`. If it has `wrap_func_with_mlflow_trace()` and a framework autolog, it's Level B. If it has `wrap_func_with_mlflow_trace()` but no framework autolog, it's Level C. If it has neither, it's Level A.

## Important

You must execute every step yourself — do NOT tell the user to do it manually or suggest they run commands. You are responsible for running all commands, starting servers, sending requests, and inspecting traces. Do not stop partway through and summarize what the user should do next.

## Steps

### 1. Code review

Read and follow `.claude/skills/review-tracing-code/SKILL.md` yourself. Read the agent's `tracing.py`, `main.py`, and any manual wrapping files. Check each item in the review checklist and produce the code review report.

### 2. Live trace testing

Read and follow `.claude/skills/test-tracing/SKILL.md` yourself. This means YOU must:
- Check if MLflow is installed and install it if not
- Set up the agent's `.env` from `.env.example`
- Start the MLflow server (finding an open port)
- Start the agent
- Send test requests (both streaming and non-streaming)
- Query the MLflow API to verify traces appeared
- Inspect spans and validate them

Do not skip any of these steps or ask the user to do them.

### 3. Combined report

Combine the outputs from both steps into a single verification report:

```text
## Tracing Verification Report: <agent_name>

### Code Review
<output from review-tracing-code>

### Live Test Results
<output from test-tracing>

### Overall Status: PASS / FAIL
```

If FAIL, list specific issues and which skill to re-run to fix them (e.g., "Missing tool wrapping in streaming path — re-run `add-manual-tracing`").

## Self-Update

Before finishing, check whether this skill file needs updating. If any of the following are true, **propose the specific changes to the user** and only update this file if they approve:

- You deviated from these instructions because they were inaccurate, outdated, or insufficient — and your deviation worked.
- You encountered a new pattern not covered here (e.g., a framework that uses OpenTelemetry instead of autolog, or a new provider path).
- File paths, function names, or API patterns referenced here have changed.
- A step didn't work as described and needed a different approach.

If nothing needed changing, move on.
