# CrewAI Websearch Agent - Behavioral Tests

## Running

All six MLflow env vars are required for OpenShift MLflow:

```bash
CREWAI_WEBSEARCH_AGENT_URL=https://<route> \
MLFLOW_TRACKING_URI=<uri> \
MLFLOW_EXPERIMENT_NAME=<experiment> \
MLFLOW_TRACKING_TOKEN=$(oc whoami -t) \
MLFLOW_WORKSPACE=<namespace> \
MLFLOW_TRACKING_INSECURE_TLS=true \
pytest agents/crewai/templates/websearch_agent/tests/behavioral/ -m crewai_websearch -v
```

## Known issue: intermittent HTTP 500 ("Invalid response from LLM call")

CrewAI's multi-step ReAct loop makes **multiple sequential LLM calls** per user request (agent reasoning, tool call, observation, final answer). After the tool-use loop, CrewAI makes one final `llm.call()` to produce the answer (`crewai/utilities/agent_utils.py:291`). If the model returns an empty completion on **any** of these internal calls, CrewAI raises a hard `ValueError("Invalid response from LLM call - None or empty.")` with no retry.

The other agents in this repo are not affected:

- **LangGraph** uses LangChain's chat model, which has more robust response parsing and retry logic.
- **Vanilla Python (OpenAI Responses)** uses the OpenAI SDK directly, which raises specific API errors rather than empty responses.

The `vllm-20b` model endpoint occasionally returns empty completions. Because CrewAI makes more LLM round-trips per request than the other agents, it has a higher probability of hitting an empty response on at least one call. This is a model reliability issue amplified by CrewAI's architecture, not a test or tracing problem.

### Impact on test results

- `test_tool_selection_accuracy` and `test_tool_call_has_valid_args` may fail with HTTP 500 when the model returns empty on any internal LLM call.
- `test_pass_at_k_tool_usage` runs 8 iterations; if most hit 500s, the pass rate drops below the 0.85 threshold.
- Tests that don't trigger tool use (greetings, coherence) are less affected since they require fewer LLM round-trips.
