# Adding a New EvalHub Agent Integration

How to add a new agent to the EvalHub on-cluster evaluation pipeline.

For behavioral test coverage (pytest-based, inner loop), see
[Adding Behavioral Tests](./adding-behavioral-tests.md). For the full
adapter architecture and end-to-end walkthrough, see the
[EvalHub Adapter README](../evals/evalhub_adapter/README.md).

## Prerequisites

- Agent is deployed with `/chat/completions` (JSON + SSE) and `/health`
- EvalHub adapter provider is registered
- Push access to a container registry

## 1. Create Fixture Queries

```bash
mkdir -p agents/<framework>/<agent_name>/evalhub
```

Create `evalhub/tool_use.yaml`:

```yaml
queries:
  - query: "A question that should trigger tool_a"
    expected_tools: ["tool_a"]
    expected_elements: ["keyword_from_tool_output"]

  - query: "A question that should trigger both tools"
    expected_tools: ["tool_a", "tool_b"]
    expected_elements: ["keyword_a", "keyword_b"]

  - query: "Hello, how are you today?"
    expected_tools: []
    expected_elements: []
```

`expected_tools` must match the agent's `@tool` function names exactly.
Include at least one no-tool query and one multi-tool query.

Existing fixtures:

- `agents/langgraph/react_agent/evalhub/tool_use.yaml`
- `agents/vanilla_python/openai_responses_agent/evalhub/tool_use.yaml`
- `agents/crewai/websearch_agent/evalhub/tool_use.yaml`
- `agents/langgraph/agentic_rag/evalhub/tool_use.yaml`

## 2. Add COPY Line to Containerfile

In `evals/evalhub_adapter/Containerfile`, add a `COPY` for your fixtures
and extend the build-time assertion:

```dockerfile
COPY agents/<framework>/<agent_name>/evalhub/ ./fixtures/<short_name>/
```

```dockerfile
RUN python -c "from pathlib import Path; assert Path('fixtures/<short_name>/tool_use.yaml').exists()"
```

`<short_name>` should be unique (e.g. `crewai_websearch`).

## 3. Create Eval Submission YAML

Create `evals/evalhub_adapter/eval-<agent_name>.yaml`:

```yaml
name: agentic-tool-use-<agent-name>
description: EvalHub orchestration run for <framework> <agent_name>
model:
  name: <framework>-<agent-name>
  url: https://<agent-route>
benchmarks:
  - id: agentic-tool-use
    provider_id: <provider-id-from-registration>
    parameters:
      known_tools: ["tool_a", "tool_b"]
      forbidden_actions: ["shell execution"]
      max_latency_seconds: 8.0
      timeout_seconds: 45.0
      verify_ssl: true
      fixtures_path: fixtures/<short_name>
      mlflow_tracking_uri: https://<mlflow-route>
      mlflow_experiment_name: <unique-run-experiment>
      mlflow_trace_experiment_name: <agent-experiment>
```

- `model.url` — agent base URL, not the `/chat/completions` path
- `fixtures_path` — must match `<short_name>` from step 2
- `provider_id` — from `evalhub providers list`

See `evals/evalhub_adapter/eval-react-agent.yaml.example` and
`eval-openai-responses-agent.yaml.example` for working examples. Full parameter
reference is in the [adapter README](../evals/evalhub_adapter/README.md#jobspec-parameters).

## 4. Rebuild and Push the Adapter Image

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
ADAPTER_IMAGE="quay.io/<your-user>/evalhub-agentic-adapter:${IMAGE_TAG}"

podman build -t "${ADAPTER_IMAGE}" -f evals/evalhub_adapter/Containerfile .
podman push "${ADAPTER_IMAGE}"
```

Re-register the provider if the image tag changed.

## 5. Submit and Verify

```bash
evalhub eval run --config evals/evalhub_adapter/eval-<agent_name>.yaml --wait --poll-interval 5
evalhub eval results <job-id> --format json
```

Metrics and result interpretation are documented in the
[adapter README](../evals/evalhub_adapter/README.md#8-interpreting-results).

## Files Changed

| File | Action |
|------|--------|
| `agents/<framework>/<agent_name>/evalhub/tool_use.yaml` | Create |
| `evals/evalhub_adapter/Containerfile` | Edit — add `COPY` + assertion |
| `evals/evalhub_adapter/eval-<agent_name>.yaml` | Create |
| `evals/evalhub_adapter/README.md` | Edit — note new agent under "What works now" |
