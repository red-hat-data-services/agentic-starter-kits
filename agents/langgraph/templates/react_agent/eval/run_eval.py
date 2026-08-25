"""MLflow GenAI evaluation script.

Reads existing traces from MLflow and evaluates them using scorers
configured in eval_config.yaml.

Usage:
    make eval
"""

import importlib
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
        return yaml.safe_load(f)


def load_eval_data(path: str | None = None) -> list[dict]:
    """Load golden queries with expectations from YAML."""
    if path is None:
        path = str(Path(__file__).parent / "eval_data.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("queries", [])


def generate_traces(eval_data: list[dict], agent_url: str) -> None:
    """Send golden queries to the running agent to generate traces."""
    print(f"Sending {len(eval_data)} golden queries to {agent_url}...")
    for query in eval_data:
        question = query["inputs"]["question"]
        response = httpx.post(
            f"{agent_url}/chat/completions",
            json={"messages": [{"role": "user", "content": question}], "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        print(f"  -> {question}")
    print(f"Generated {len(eval_data)} traces.\n")


def attach_expectations(traces, eval_data):
    """Match traces to golden queries by input text and log expectations.

    Returns the set of trace IDs that matched a golden query.
    """
    matched_ids = set()
    for trace in traces:
        request = str(trace.info.request_preview or "")
        for query in eval_data:
            question = query["inputs"]["question"]
            if question.lower() in request.lower():
                expectations = query.get("expectations", {})
                for name, value in expectations.items():
                    mlflow.log_expectation(
                        trace_id=trace.info.trace_id,
                        name=name,
                        value=value,
                    )
                matched_ids.add(trace.info.trace_id)
                break

    print(f"Matched {len(matched_ids)}/{len(traces)} traces to golden queries with expectations.")
    return matched_ids


def resolve_scorer(entry: dict, judge_model: str):
    """Resolve a scorer entry from config into a scorer instance."""
    env_flag = entry.get("enabled_by_env")
    if env_flag and os.getenv(env_flag, "").lower() != "true":
        return None

    module = importlib.import_module(entry["module"])
    cls = getattr(module, entry["name"])
    return cls(model=judge_model)


def get_scorers(config: dict) -> list:
    """Build the scorer list from eval_config.yaml."""
    judge_model = os.getenv("EVAL_JUDGE_MODEL", "openai:/gpt-4o-mini")
    scorers = []

    for entry in config["scorers"].get("core", []):
        s = resolve_scorer(entry, judge_model)
        if s:
            scorers.append(s)

    for entry in config["scorers"].get("use_case") or []:
        s = resolve_scorer(entry, judge_model)
        if s:
            scorers.append(s)

    guidelines = config["scorers"].get("guidelines", [])
    if guidelines:
        scorers.append(Guidelines(
            name="domain_guidelines",
            model=judge_model,
            guidelines=guidelines,
        ))

    return scorers


def main():
    """Read traces from MLflow, attach expectations, and evaluate with scorers."""
    load_dotenv()

    judge_model = os.getenv("EVAL_JUDGE_MODEL", "openai:/gpt-4o-mini")
    judge_api_key = os.getenv("EVAL_JUDGE_API_KEY")
    judge_base_url = os.getenv("EVAL_JUDGE_BASE_URL")
    provider = judge_model.split(":/")[0] if ":/" in judge_model else "openai"

    if judge_api_key:
        provider_key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "bedrock": "AWS_ACCESS_KEY_ID",
        }
        env_key = provider_key_map.get(provider, f"{provider.upper()}_API_KEY")
        os.environ[env_key] = judge_api_key
    if judge_base_url and provider == "openai":
        os.environ["OPENAI_BASE_URL"] = judge_base_url

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        print("ERROR: MLFLOW_TRACKING_URI is not set. Cannot read traces.")
        print("Set it in .env and ensure the agent has been run with tracing enabled.")
        return

    mlflow.set_tracking_uri(tracking_uri)

    experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME")
    if not experiment_name:
        print("ERROR: MLFLOW_EXPERIMENT_NAME is not set.")
        return

    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment is None:
        print(f"ERROR: Experiment '{experiment_name}' not found on MLflow server.")
        print("Run the agent first to create traces, then re-run eval.")
        return

    mlflow.set_experiment(experiment_name)

    eval_data = load_eval_data()
    agent_url = os.getenv("AGENT_URL", "http://localhost:8000")

    run_start_ms = int(time.time() * 1000)

    if eval_data:
        generate_traces(eval_data, agent_url)

    expected_count = len(eval_data) if eval_data else 0
    traces = []
    for attempt in range(10):
        traces = mlflow.search_traces(
            locations=[experiment.experiment_id],
            return_type="list",
            filter_string=f"trace.timestamp_ms > {run_start_ms}",
        )
        if len(traces) >= expected_count:
            break
        time.sleep(2)

    if not traces:
        print(f"No traces found in experiment '{experiment_name}' for this run.")
        print("Ensure the agent is running with tracing enabled, then re-run eval.")
        return

    print(f"Found {len(traces)} traces from this run to evaluate.")

    if eval_data:
        matched_ids = attach_expectations(traces, eval_data)
        traces = mlflow.search_traces(
            locations=[experiment.experiment_id],
            return_type="list",
            filter_string=f"trace.timestamp_ms > {run_start_ms}",
        )
        traces = [t for t in traces if t.info.trace_id in matched_ids]

    config = load_eval_config()
    scorers = get_scorers(config)
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
