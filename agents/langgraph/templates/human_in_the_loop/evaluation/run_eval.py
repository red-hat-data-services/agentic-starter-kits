"""MLflow GenAI evaluation script.

Reads existing traces from MLflow and evaluates them using scorers
configured in eval_config.yaml.

Usage:
    make eval
"""

import importlib
import inspect
import json
import os
import time
from pathlib import Path

import httpx
import mlflow
import yaml
from dotenv import load_dotenv
from mlflow.genai.scorers import Guidelines


def load_eval_config(path: str | None = None) -> dict:
    """Load scorer configuration from YAML."""
    if path is None:
        path = str(Path(__file__).parent / "eval_config.yaml")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_eval_data(path: str | None = None) -> list[dict]:
    """Load golden queries with expectations from YAML."""
    if path is None:
        path = str(Path(__file__).parent / "eval_data.yaml")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("queries") or []


def _find_duplicate_questions(eval_data: list[dict]) -> list[str]:
    """Return duplicate question text from eval data, preserving first duplicate order."""
    seen = set()
    duplicates = []

    for query in eval_data:
        question = query["inputs"]["question"]
        if question in seen and question not in duplicates:
            duplicates.append(question)
        seen.add(question)

    return duplicates


def validate_eval_data(eval_data: list[dict]) -> None:
    """Validate eval data before sending requests to the agent."""
    duplicate_questions = _find_duplicate_questions(eval_data)
    if duplicate_questions:
        print("ERROR: Duplicate questions found in evaluation/eval_data.yaml.")
        print(
            "Trace matching uses exact question text, so each golden query must be unique."
        )
        for question in duplicate_questions:
            print(f"  - {question}")
        raise SystemExit(1)


def _get_int_env(name: str, default: int) -> int:
    """Read an integer env var, exiting with a friendly message if invalid or negative."""
    value = os.getenv(name, str(default))
    try:
        result = int(value)
    except ValueError:
        print(f"ERROR: {name}={value!r} is not a valid integer.")
        raise SystemExit(1)
    if result < 0:
        print(f"ERROR: {name}={result} must not be negative.")
        raise SystemExit(1)
    return result


def generate_traces(eval_data: list[dict], agent_url: str) -> None:
    """Send golden queries to the running agent to generate traces."""
    request_timeout = _get_int_env("EVAL_REQUEST_TIMEOUT", 60)
    print(f"Sending {len(eval_data)} golden queries to {agent_url}...")
    for query in eval_data:
        question = query["inputs"]["question"]
        try:
            response = httpx.post(
                f"{agent_url}/chat/completions",
                json={
                    "messages": [{"role": "user", "content": question}],
                    "stream": False,
                },
                timeout=request_timeout,
            )
            response.raise_for_status()
            body = response.json()
            choices = body.get("choices") or []
            if choices:
                finish_reason = choices[0].get("finish_reason")
                if finish_reason == "pending_approval":
                    print(
                        f"\nERROR: Agent returned 'pending_approval' for: {question}"
                        "\nThe HITL template requires human approval for this query."
                        "\nEval cannot score incomplete responses. Either approve the "
                        "pending request or adjust eval_data.yaml to avoid queries "
                        "that trigger approval."
                    )
                    raise SystemExit(1)
        except httpx.ConnectError:
            print(
                f"\nERROR: Could not connect to agent at {agent_url}."
                "\nIs the agent running? Start it with: make run-app"
            )
            raise SystemExit(1)
        except httpx.TimeoutException:
            print(
                f"\nERROR: Agent at {agent_url} did not respond within {request_timeout}s."
                "\nThe agent may be overloaded or the model endpoint may be slow."
            )
            raise SystemExit(1)
        except httpx.HTTPStatusError as e:
            print(f"\nERROR: Agent returned HTTP {e.response.status_code}.")
            print("Check the agent logs for details.")
            raise SystemExit(1)
        except httpx.RequestError as e:
            print(f"\nERROR: Request to {agent_url} failed: {e}")
            raise SystemExit(1)
        print(f"  -> {question}")
    print(f"Generated {len(eval_data)} traces.\n")


def _extract_question(trace):
    """Extract the user question from a trace's request data."""
    try:
        request = json.loads(trace.data.request)
        return request["messages"][0]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None


def attach_expectations(traces, eval_data):
    """Match traces to golden queries by content and log expectations.

    Each golden query's question is matched against the question extracted
    from trace.data.request using exact string comparison. Interleaved
    traces from concurrent traffic with different questions are ignored,
    but concurrent requests with identical question text could mis-associate.

    Returns a mapping of matched trace IDs to expectation names logged for each trace.
    """
    expectation_names_by_trace_id = {}

    for query in eval_data:
        question = query["inputs"]["question"]
        for trace in traces:
            if trace.info.trace_id in expectation_names_by_trace_id:
                continue
            if _extract_question(trace) == question:
                expectations = query.get("expectations", {})
                for name, value in expectations.items():
                    mlflow.log_expectation(
                        trace_id=trace.info.trace_id,
                        name=name,
                        value=value,
                    )
                expectation_names_by_trace_id[trace.info.trace_id] = set(
                    expectations.keys()
                )
                break

    print(
        f"Matched {len(expectation_names_by_trace_id)}/{len(traces)} traces "
        "to golden queries with expectations."
    )
    return expectation_names_by_trace_id


def _trace_has_expectations(trace, expected_names: set[str]) -> bool:
    """Return whether a re-fetched trace includes all expected expectation names."""
    if not expected_names:
        return True

    assessments = trace.search_assessments(type="expectation")
    assessment_names = {getattr(assessment, "name", None) for assessment in assessments}
    return expected_names.issubset(assessment_names)


def refetch_matched_traces_with_expectations(
    experiment_id: str,
    baseline_ms: int,
    expectation_names_by_trace_id: dict[str, set[str]],
    timeout: int,
    poll_interval: int,
):
    """Re-fetch matched traces until logged expectations are visible."""
    deadline = time.monotonic() + timeout
    matched_ids = set(expectation_names_by_trace_id)
    matched_traces = []

    while True:
        traces = mlflow.search_traces(
            locations=[experiment_id],
            return_type="list",
            filter_string=f"trace.timestamp_ms > {baseline_ms}",
        )
        matched_traces = [t for t in traces if t.info.trace_id in matched_ids]
        ready_traces = [
            trace
            for trace in matched_traces
            if _trace_has_expectations(
                trace, expectation_names_by_trace_id[trace.info.trace_id]
            )
        ]

        if len(ready_traces) == len(matched_ids):
            return ready_traces

        if time.monotonic() >= deadline:
            missing = matched_ids - {t.info.trace_id for t in ready_traces}
            print(
                "ERROR: Timed out waiting for logged expectations to become "
                f"visible on {len(missing)} trace(s)."
            )
            raise SystemExit(1)

        time.sleep(poll_interval)


def filter_matching_traces_or_exit(
    traces,
    golden_questions: set[str],
    expected_count: int,
    trace_timeout: int,
    experiment_name: str,
):
    """Filter traces to golden-query matches, failing if the batch is incomplete."""
    matched_traces = [t for t in traces if _extract_question(t) in golden_questions]

    if not traces:
        print(f"ERROR: No traces found in experiment '{experiment_name}' for this run.")
        print("Ensure the agent is running with tracing enabled, then re-run eval.")
        raise SystemExit(1)

    if len(matched_traces) < expected_count:
        print(
            f"ERROR: Expected {expected_count} matching traces but only found "
            f"{len(matched_traces)} after {trace_timeout}s."
        )
        print(
            "Some queries may not have been recorded or traces may still be incomplete."
        )
        raise SystemExit(1)

    return matched_traces


def resolve_scorer(entry: dict, judge_model: str):
    """Resolve a scorer entry from config into a scorer instance."""
    env_flag = entry.get("enabled_by_env")
    if env_flag and os.getenv(env_flag, "").lower() != "true":
        return None

    model = judge_model
    if entry.get("model_env"):
        model = os.getenv(entry["model_env"], model)

    module = importlib.import_module(entry["module"])
    cls_or_obj = getattr(module, entry["name"])

    if inspect.isclass(cls_or_obj):
        try:
            init_params = inspect.signature(cls_or_obj.__init__).parameters
        except (TypeError, ValueError):
            init_params = {}
        accepts_model = "model" in init_params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in init_params.values()
        )
        return cls_or_obj(model=model) if accepts_model else cls_or_obj()
    return cls_or_obj


def _add_scorer(scorers: list, entry: dict, judge_model: str) -> None:
    """Resolve a scorer entry and append it, skipping with a warning on config errors."""
    try:
        s = resolve_scorer(entry, judge_model)
    except (ModuleNotFoundError, AttributeError, TypeError, KeyError) as e:
        name = entry.get("name") if isinstance(entry, dict) else "<invalid entry>"
        print(f"WARNING: Could not load scorer '{name}': {e}. Skipping.")
        return
    if s:
        scorers.append(s)


def get_scorers(config: dict, judge_model: str) -> list:
    """Build the scorer list from eval_config.yaml."""
    scorers = []
    scorer_config = config.get("scorers", {})

    for entry in scorer_config.get("core") or []:
        _add_scorer(scorers, entry, judge_model)

    for entry in scorer_config.get("use_case") or []:
        _add_scorer(scorers, entry, judge_model)

    guidelines = scorer_config.get("guidelines") or []
    if guidelines:
        scorers.append(
            Guidelines(
                name="domain_guidelines",
                model=judge_model,
                guidelines=guidelines,
            )
        )

    return scorers


def main():
    """Read traces from MLflow, attach expectations, and evaluate with scorers."""
    load_dotenv()

    judge_model = os.getenv("EVAL_JUDGE_MODEL", "openai:/gpt-4o-mini")
    judge_api_key = os.getenv("EVAL_JUDGE_API_KEY")
    judge_base_url = os.getenv("EVAL_JUDGE_BASE_URL")
    provider = judge_model.split(":/")[0] if ":/" in judge_model else "openai"

    if judge_api_key:
        os.environ[f"{provider.upper()}_API_KEY"] = judge_api_key
    if judge_base_url:
        env_var = f"{provider.upper()}_BASE_URL"
        os.environ[env_var] = judge_base_url
        print(f"  Set {env_var} for judge model base URL")

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        print("ERROR: MLFLOW_TRACKING_URI is not set. Cannot read traces.")
        print("Set it in .env and ensure the agent has been run with tracing enabled.")
        raise SystemExit(1)

    mlflow.set_tracking_uri(tracking_uri)

    experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME")
    if not experiment_name:
        print("ERROR: MLFLOW_EXPERIMENT_NAME is not set.")
        raise SystemExit(1)

    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment is None:
        print(f"ERROR: Experiment '{experiment_name}' not found on MLflow server.")
        print("Run the agent first to create traces, then re-run eval.")
        raise SystemExit(1)

    mlflow.set_experiment(experiment_name)

    config = load_eval_config()
    scorers = get_scorers(config, judge_model)
    print(f"Loaded {len(scorers)} scorers from eval_config.yaml.")

    eval_data = load_eval_data()
    if not eval_data:
        print("ERROR: No golden queries in evaluation/eval_data.yaml.")
        print("Add at least one query under 'queries:' before running make eval.")
        raise SystemExit(1)

    validate_eval_data(eval_data)
    golden_questions = {q["inputs"]["question"] for q in eval_data}

    agent_url = os.getenv("AGENT_URL", "http://localhost:8000")

    existing = mlflow.search_traces(
        locations=[experiment.experiment_id],
        return_type="list",
        max_results=1,
        order_by=["timestamp_ms DESC"],
    )
    baseline_ms = existing[0].info.timestamp_ms if existing else 0

    generate_traces(eval_data, agent_url)

    expected_count = len(eval_data)
    trace_timeout = _get_int_env("EVAL_TRACE_TIMEOUT", 60)
    poll_interval = max(_get_int_env("EVAL_POLL_INTERVAL", 4), 1)
    deadline = time.monotonic() + trace_timeout

    traces = []
    while True:
        traces = mlflow.search_traces(
            locations=[experiment.experiment_id],
            return_type="list",
            filter_string=f"trace.timestamp_ms > {baseline_ms}",
        )
        if len(traces) >= expected_count:
            matched = [t for t in traces if _extract_question(t) in golden_questions]
            if len(matched) >= expected_count:
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0)))

    traces = filter_matching_traces_or_exit(
        traces=traces,
        golden_questions=golden_questions,
        expected_count=expected_count,
        trace_timeout=trace_timeout,
        experiment_name=experiment_name,
    )
    print(f"Found {len(traces)} matching traces from this run to evaluate.")

    expectation_names_by_trace_id = attach_expectations(traces, eval_data)
    traces = refetch_matched_traces_with_expectations(
        experiment_id=experiment.experiment_id,
        baseline_ms=baseline_ms,
        expectation_names_by_trace_id=expectation_names_by_trace_id,
        timeout=trace_timeout,
        poll_interval=poll_interval,
    )

    if not traces:
        print("ERROR: No traces matched golden queries. Skipping evaluation.")
        print("This can happen if traces were not fully written when matching ran.")
        raise SystemExit(1)

    print(f"Evaluating {len(traces)} traces with {len(scorers)} scorers...")

    with mlflow.start_run(run_name="eval-run"):
        results = mlflow.genai.evaluate(
            data=traces,
            scorers=scorers,
        )

    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    for metric_name, value in sorted(results.metrics.items()):
        print(f"  {metric_name}: {value}")
    print("=" * 60)
    print(f"\nDetailed results logged to MLflow experiment: {experiment_name}")


if __name__ == "__main__":
    main()
