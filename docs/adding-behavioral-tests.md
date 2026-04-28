# Adding Behavioral Tests for an Agent

This guide explains how to add behavioral tests for an agent that doesn't have test coverage yet.

## Prerequisites

- The agent is deployed and exposes the standard `/chat/completions` and `/health` endpoints
- You know what tools the agent has (check its `src/` directory for `@tool` decorators or tool definitions)
- Test dependencies are installed: `uv pip install -e ".[test]"`

## 1. Create the Directory Structure

```bash
mkdir -p agents/<framework>/<agent>/tests/behavioral/fixtures
```

For example, the LangGraph ReAct agent tests live at:

```
agents/langgraph/react_agent/tests/behavioral/
├── conftest.py
├── test_tool_usage.py
├── test_response_quality.py
├── test_cost_latency.py
├── test_reliability.py
└── fixtures/
    └── golden_queries.yaml
```

## 2. Create conftest.py

The conftest defines fixtures specific to your agent. Because agent tests live under `agents/` (a separate directory tree from `tests/behavioral/`), pytest's conftest discovery won't find the shared fixtures. You must define `http_client` and `eval_config` locally. At minimum you need:

- `agent_url` — reads from a new env var specific to your agent
- `http_client` — must be redefined locally (not inherited from `tests/behavioral/conftest.py`)
- `eval_config` — resolves the path to `tests/behavioral/configs/thresholds.yaml` relative to the repo root (adjust `.parents[N]` based on your agent's directory depth)
- `known_tools` — lists the tools in the agent's schema (used by hallucination detection)
- `agent_thresholds` — pulls from the shared `eval_config` fixture
- `run_eval` — overrides the root fixture to add MLflow trace enrichment

See existing agent implementations for working examples:

- `agents/langgraph/react_agent/tests/behavioral/conftest.py`
- `agents/vanilla_python/openai_responses_agent/tests/behavioral/conftest.py`

## 3. Add Thresholds

Add a section for your agent in `tests/behavioral/configs/thresholds.yaml`:

```yaml
my_agent:
  tool_selection_accuracy: 0.85
  response_coherence_accuracy: 0.75
  max_latency_p95: 10.0
  pass_at_k: 8
```

## 4. Create Golden Queries

Create `fixtures/golden_queries.yaml` with test inputs for your agent:

```yaml
queries:
  - query: "A question that should trigger tool_a"
    expected_tools: ["tool_a"]
    expected_elements: ["keyword_from_tool_output"]
    difficulty: easy
    category: factual

  - query: "Hello"
    expected_tools: []
    expected_elements: []
    difficulty: easy
    category: greeting
```

## 5. Write Test Files

There are four standard test files. Each one uses pytest markers to describe **what** is being tested, not which agent:

| File | Marker | What it tests |
|------|--------|---------------|
| `test_tool_usage.py` | `@pytest.mark.<agent>` | Correct tool selection, no hallucinated tools, valid args |
| `test_response_quality.py` | `@pytest.mark.<agent>` | Plan coherence, completeness, multi-tool synthesis |
| `test_cost_latency.py` | `@pytest.mark.<agent>` | Response time within threshold |
| `test_reliability.py` | `@pytest.mark.<agent>`, `@pytest.mark.slow` | pass@k consistency over repeated runs |

See the existing implementations for reference:

- `agents/langgraph/react_agent/tests/behavioral/` (single tool: `search`)
- `agents/vanilla_python/openai_responses_agent/tests/behavioral/` (two tools: `search_price`, `search_reviews`)

## 6. Register the Agent Marker

Add your agent marker to `pyproject.toml` under the agent markers section:

```toml
markers = [
    # Agent markers
    "langgraph_react: ...",
    "vanilla_python: ...",
    "my_agent: My Agent description (tool_a + tool_b)",
    ...
]
```

## 7. Add the Env Var to the README

Add your agent's URL env var to the table in the Behavioral Tests section of the root `README.md`.

## 8. Verify

```bash
# Check tests are discovered
pytest agents/<framework>/<agent>/tests/behavioral/ --collect-only

# Run against a deployed agent
MY_AGENT_URL=https://my-agent.example.com pytest agents/<framework>/<agent>/tests/behavioral/ -v
```
