# Adding Behavioral Tests for an Agent

This guide explains how to add behavioral tests for an agent that doesn't have test coverage yet.

## Prerequisites

- The agent is deployed and exposes the standard `/chat/completions` and `/health` endpoints
- You know what tools the agent has (check its `src/` directory for `@tool` decorators or tool definitions)
- Test dependencies are installed: `uv pip install -e ".[test]"`

## 1. Create the Directory Structure

```bash
mkdir -p agents/<framework>/templates/<agent>/tests/behavioral/fixtures
```

For example, the LangGraph ReAct agent tests live at:

```text
agents/langgraph/templates/react_agent/tests/behavioral/
├── conftest.py
├── test_tool_usage.py
├── test_response_quality.py
├── test_cost_latency.py
├── test_reliability.py
└── fixtures/
    └── golden_queries.yaml
```

The deterministic cluster runner also expects template-layout agent IDs. Use
`langgraph/templates/react_agent`, not the legacy `langgraph/react_agent` form.

## 2. Create conftest.py

The conftest defines fixtures specific to your agent. Because agent tests live under `agents/` (a separate directory tree from `tests/behavioral/`), pytest's conftest discovery won't find the shared fixtures. You must define `http_client` and `eval_config` locally. At minimum you need:

- `agent_url` — reads from a new env var specific to your agent
- `http_client` — must be redefined locally (not inherited from `tests/behavioral/conftest.py`)
- `eval_config` — resolves the path to `tests/behavioral/configs/thresholds.yaml` relative to the repo root (adjust `.parents[N]` based on your agent's directory depth)
- `known_tools` — lists the tools in the agent's schema (used by hallucination detection)
- `agent_thresholds` — pulls from the shared `eval_config` fixture
- `run_eval` — overrides the root fixture to add MLflow trace enrichment

**`load_golden()` helper:** Import the shared loader from `harness.fixtures` and create a thin wrapper that binds `fixtures_dir` to `Path(__file__).parent / "fixtures"`:

```python
from pathlib import Path
from typing import Any

from harness.fixtures import load_golden as _load_golden_from

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def load_golden(category: str | None = None) -> list[dict[str, Any]]:
    return _load_golden_from(FIXTURES_DIR, category)
```

See existing agent implementations for working examples:

- `agents/langgraph/templates/react_agent/tests/behavioral/conftest.py`
- `agents/vanilla_python/templates/openai_responses_agent/tests/behavioral/conftest.py`
- `agents/autogen/templates/mcp_agent/tests/behavioral/conftest.py`
- `agents/crewai/templates/websearch_agent/tests/behavioral/conftest.py`
- `agents/langgraph/templates/agentic_rag/tests/behavioral/conftest.py`
- `agents/langgraph/templates/react_with_database_memory/tests/behavioral/conftest.py`
- `agents/langgraph/templates/human_in_the_loop/tests/behavioral/conftest.py`
- `agents/google/templates/adk/tests/behavioral/conftest.py`
- `agents/langflow/templates/simple_tool_calling_agent/tests/behavioral/conftest.py` — **non-standard adapter**: uses `api_format="langflow_run"` + `flow_id` instead of `/chat/completions`, no MLflow enrichment (tool_calls from `content_blocks`). Follow the standard pattern above unless your agent also uses a non-standard API.
- `agents/a2a/templates/langgraph_crewai_agent/tests/behavioral/conftest.py` — A2A multi-pod agent (LangGraph orchestrator + CrewAI specialist); tests target the LangGraph `/chat/completions` shim; tool_calls via MLflow enrichment.

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

- `agents/langgraph/templates/react_agent/tests/behavioral/` (single tool: `search`)
- `agents/vanilla_python/templates/openai_responses_agent/tests/behavioral/` (two tools: `search_price`, `search_reviews`)
- `agents/autogen/templates/mcp_agent/tests/behavioral/` (two tools via MCP: `add`, `sub`)
- `agents/crewai/templates/websearch_agent/tests/behavioral/` (single tool: `Web Search`)
- `agents/langgraph/templates/agentic_rag/tests/behavioral/` (single tool: `retriever`)
- `agents/langgraph/templates/react_with_database_memory/tests/behavioral/` (single tool: `search` + PostgreSQL memory)
- `agents/llamaindex/templates/websearch_agent/tests/behavioral/` (single tool: `dummy_web_search`)
- `agents/langgraph/templates/human_in_the_loop/tests/behavioral/` (single tool: `create_file` with HITL approval workflow)
- `agents/langflow/templates/simple_tool_calling_agent/tests/behavioral/` (three tools: `get_forecast`, `search_parks`, `park_alerts` — Langflow `api_format`)
- `agents/google/templates/adk/tests/behavioral/` (single tool: `dummy_web_search`)
- `agents/a2a/templates/langgraph_crewai_agent/tests/behavioral/` (single tool: `ask_crew_specialist` — A2A multi-pod delegation)

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
pytest agents/<framework>/templates/<agent>/tests/behavioral/ --collect-only

# Run against a deployed agent
MY_AGENT_URL=https://my-agent.example.com pytest agents/<framework>/templates/<agent>/tests/behavioral/ -v
```
