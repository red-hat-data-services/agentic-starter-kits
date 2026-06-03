"""EvalHub framework adapter for agentic evaluations.

Wraps our existing pytest-based eval harness (harness/runner.py + harness/scorers/)
so agentic evals run through EvalHub's orchestration layer on Kubernetes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import httpx
from evalhub.adapter import (
    AdapterSettings,
    DefaultCallbacks,
    ErrorInfo,
    EvaluationResult,
    FrameworkAdapter,
    JobCallbacks,
    JobPhase,
    JobResults,
    JobSpec,
    JobStatus,
    JobStatusUpdate,
    MessageInfo,
)
from harness.runner import TaskResult, run_task
from harness.scorers import Score
from harness.scorers.latency import score_latency
from harness.scorers.plan_coherence import score_completeness, score_plan_coherence
from harness.scorers.safety import (
    score_pii_leakage,
    score_policy_adherence,
    score_prompt_injection_resistance,
)
from harness.scorers.tool_sequence import (
    score_hallucinated_tools,
    score_tool_call_validity,
    score_tool_selection,
    score_tool_sequence,
)

from .config import AgenticEvalParams, job_spec_to_task_config
from .evaluations import QuerySpec, get_benchmark, load_queries, resolve_scorers

try:
    from harness.mlflow_client import MLflowTraceClient
except ImportError:
    MLflowTraceClient = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


async def _get_langflow_token(base_url: str, client: httpx.AsyncClient) -> str:
    """Obtain an auth token from Langflow's auto_login endpoint."""
    url = f"{base_url.rstrip('/')}/api/v1/auto_login"
    resp = await client.get(url, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ValueError(
            "Langflow auto_login response missing 'access_token'. "
            "Ensure the Langflow instance has LANGFLOW_AUTO_LOGIN=true. "
            f"Response keys: {list(data.keys())}"
        )
    return token


class AgenticEvalAdapter(FrameworkAdapter):
    """EvalHub adapter that runs our agentic eval harness."""

    def run_benchmark_job(self, config: JobSpec, callbacks: JobCallbacks) -> JobResults:
        """Entry point called by EvalHub. Bridges sync→async.

        Uses a thread-pool fallback when called from within an existing event
        loop (e.g. if EvalHub's orchestrator is itself async).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self._run_async(config, callbacks))
                return future.result()
        return asyncio.run(self._run_async(config, callbacks))

    async def _run_async(self, config: JobSpec, callbacks: JobCallbacks) -> JobResults:
        """Async implementation of the eval job."""

        _report(
            callbacks,
            JobStatus.RUNNING,
            JobPhase.INITIALIZING,
            0.0,
            "Validating configuration",
        )
        agent_url = config.model.url
        params = AgenticEvalParams.from_dict(config.parameters)

        # Initialize MLflow trace enrichment if configured
        mlflow = None
        if (
            MLflowTraceClient is not None
            and params.mlflow_tracking_uri
            and params.mlflow_experiment_name
        ):
            if not os.environ.get("MLFLOW_TRACKING_TOKEN"):
                logger.warning(
                    "MLFLOW_TRACKING_TOKEN is not set. MLflow trace enrichment "
                    "and run logging will fail if the server requires auth "
                    "(e.g. RHOAI MLflow). EvalHub does not support secretKeyRef "
                    "in provider runtime Env — pass the token as a literal value."
                )

            trace_experiment = params.mlflow_trace_experiment_name
            mlflow = MLflowTraceClient(params.mlflow_tracking_uri, trace_experiment)
            if mlflow.verify_connection():
                logger.info(
                    "MLflow trace enrichment enabled: %s trace_experiment=%s "
                    "run_experiment=%s",
                    params.mlflow_tracking_uri,
                    trace_experiment,
                    params.mlflow_experiment_name,
                )
            else:
                logger.warning(
                    "MLflow connection check failed — trace enrichment and "
                    "run logging may not work. Scoring will continue using "
                    "HTTP response data only."
                )

        try:
            benchmark = get_benchmark(config.benchmark_id)
        except Exception:
            _report_fatal(
                callbacks, "Invalid benchmark configuration", JobPhase.INITIALIZING
            )
            raise

        scorer_names = resolve_scorers(benchmark)

        fixtures_dir = Path(params.fixtures_path)

        _report(
            callbacks,
            JobStatus.RUNNING,
            JobPhase.LOADING_DATA,
            10.0,
            "Loading golden queries",
        )
        try:
            queries = load_queries(benchmark, fixtures_dir)
        except Exception:
            _report_fatal(
                callbacks, "Failed to load evaluation data", JobPhase.LOADING_DATA
            )
            raise

        if not queries:
            _report_fatal(
                callbacks, "No queries found in benchmark", JobPhase.LOADING_DATA
            )
            raise ValueError("No queries found in benchmark")

        _report(
            callbacks,
            JobStatus.RUNNING,
            JobPhase.RUNNING_EVALUATION,
            30.0,
            f"Running evaluations (0/{len(queries)} queries)",
        )
        start_time = time.time()
        all_scores: list[tuple[QuerySpec, list[Score]]] = []
        failed_count = 0

        async with httpx.AsyncClient(
            verify=params.verify_ssl, timeout=httpx.Timeout(params.timeout_seconds)
        ) as client:
            langflow_headers: dict[str, str] = {}
            if params.api_format == "langflow_run":
                token = await _get_langflow_token(agent_url, client)
                langflow_headers = {"Authorization": f"Bearer {token}"}

            for i, query_spec in enumerate(queries):
                progress = 30.0 + (50.0 * (i + 1) / len(queries))
                try:
                    task_config = job_spec_to_task_config(
                        agent_url=agent_url,
                        query=query_spec.query,
                        expected_tools=query_spec.expected_tools,
                        params=params,
                        model_name=config.model.name,
                        extra_headers=langflow_headers or None,
                    )
                    request_start_ms = int(time.time() * 1000)
                    result = await run_task(task_config, client=client)

                    if not result.success:
                        failed_count += 1
                        query_scores = [
                            Score(
                                name="query_error",
                                value=0.0,
                                passed=False,
                                details={
                                    "query": query_spec.query,
                                    "error": result.error or "execution_failed",
                                },
                            )
                        ]
                    else:
                        if mlflow is not None:
                            try:
                                mlflow.enrich_eval_result(
                                    result, since_ms=request_start_ms
                                )
                            except Exception:
                                logger.warning(
                                    "MLflow trace enrichment failed for query %d/%d",
                                    i + 1,
                                    len(queries),
                                    exc_info=True,
                                )

                        query_scores = _score_result(
                            result, query_spec, scorer_names, params
                        )
                    all_scores.append((query_spec, query_scores))
                except Exception:
                    logger.exception(
                        "Query %d/%d failed: %s",
                        i + 1,
                        len(queries),
                        query_spec.query[:80],
                    )
                    failed_count += 1
                    error_score = Score(
                        name="query_error",
                        value=0.0,
                        passed=False,
                        details={
                            "query": query_spec.query,
                            "error": "execution_failed",
                        },
                    )
                    all_scores.append((query_spec, [error_score]))

                _report(
                    callbacks,
                    JobStatus.RUNNING,
                    JobPhase.RUNNING_EVALUATION,
                    progress,
                    f"Evaluated {i + 1}/{len(queries)} queries",
                )

        if failed_count == len(queries):
            _report_fatal(callbacks, "All queries failed — agent may be unreachable")
            raise RuntimeError("All queries failed")

        _report(
            callbacks,
            JobStatus.RUNNING,
            JobPhase.POST_PROCESSING,
            80.0,
            "Aggregating metrics",
        )
        eval_results = _aggregate_scores(all_scores)
        overall_score = _compute_overall(eval_results)
        duration = time.time() - start_time

        _report(
            callbacks,
            JobStatus.RUNNING,
            JobPhase.PERSISTING_ARTIFACTS,
            90.0,
            "Persisting results",
        )

        mlflow_run_id = None
        if params.mlflow_tracking_uri and params.mlflow_experiment_name:
            mlflow_run_id = _log_mlflow_run(
                params.mlflow_tracking_uri,
                params.mlflow_experiment_name,
                config,
                eval_results,
                overall_score,
                duration,
                len(queries),
            )

        job_results = JobResults(
            id=config.id,
            benchmark_id=config.benchmark_id,
            benchmark_index=config.benchmark_index,
            model_name=config.model.name,
            results=eval_results,
            overall_score=overall_score,
            num_examples_evaluated=len(queries),
            duration_seconds=duration,
            mlflow_run_id=mlflow_run_id,
        )
        callbacks.report_results(job_results)

        return job_results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_result(
    result: TaskResult,
    query_spec: QuerySpec,
    scorer_names: list[str],
    params: AgenticEvalParams,
) -> list[Score]:
    """Run the requested scorers against a single task result."""
    scores: list[Score] = []

    for scorer_name in scorer_names:
        score = _run_scorer(result, query_spec, scorer_name, params)
        if score is not None:
            scores.append(score)

    return scores


def _run_scorer(
    result: TaskResult,
    query_spec: QuerySpec,
    scorer_name: str,
    params: AgenticEvalParams,
) -> Score | None:
    """Dispatch to the appropriate scorer function.

    Currently active (invoked by ``agentic-tool-use`` benchmark):
        tool_selection, tool_sequence, hallucinated_tools, tool_call_validity

    Pre-wired for future benchmarks (dispatch tested, not yet invoked on-cluster):
        plan_coherence, completeness, latency, pii_leakage,
        policy_adherence, injection_resistance
    """
    expected_tools = query_spec.expected_tools or []

    try:
        # -- Active scorers (agentic-tool-use benchmark) --
        if scorer_name == "tool_selection":
            return score_tool_selection(result, expected_tools)
        elif scorer_name == "tool_sequence":
            return score_tool_sequence(result, expected_tools)
        elif scorer_name == "hallucinated_tools":
            return score_hallucinated_tools(result, params.known_tools)
        elif scorer_name == "tool_call_validity":
            return score_tool_call_validity(result)
        # -- Pre-wired for future benchmarks --
        elif scorer_name == "plan_coherence":
            return score_plan_coherence(result)
        elif scorer_name == "completeness":
            return score_completeness(result, query_spec.expected_elements)
        elif scorer_name == "latency":
            return score_latency(result, params.max_latency_seconds)
        elif scorer_name == "pii_leakage":
            return score_pii_leakage(result)
        elif scorer_name == "policy_adherence":
            return score_policy_adherence(result, params.forbidden_actions)
        elif scorer_name == "injection_resistance":
            return score_prompt_injection_resistance(result, query_spec.query)
        else:
            logger.warning("Unknown scorer: %s", scorer_name)
            return None
    except Exception:
        logger.exception("Scorer '%s' raised an exception", scorer_name)
        return Score(
            name=scorer_name,
            value=0.0,
            passed=False,
            details={"error": "scorer_exception"},
        )


# ---------------------------------------------------------------------------
# Score → EvaluationResult aggregation
# ---------------------------------------------------------------------------


def _aggregate_scores(
    all_scores: list[tuple[QuerySpec, list[Score]]],
) -> list[EvaluationResult]:
    """Aggregate per-query scores into per-metric EvaluationResults."""
    metric_values: dict[str, list[float]] = {}
    metric_passed: dict[str, list[bool]] = {}

    for _query_spec, scores in all_scores:
        for score in scores:
            metric_values.setdefault(score.name, []).append(score.value)
            metric_passed.setdefault(score.name, []).append(score.passed)

    results: list[EvaluationResult] = []
    for metric_name, values in metric_values.items():
        mean_value = sum(values) / len(values)
        pass_rate = sum(metric_passed[metric_name]) / len(metric_passed[metric_name])
        results.append(
            EvaluationResult(
                metric_name=metric_name,
                metric_value=round(mean_value, 4),
                metric_type="float",
                num_samples=len(values),
                metadata={
                    "pass_rate": round(pass_rate, 4),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                },
            )
        )

    return results


def _compute_overall(eval_results: list[EvaluationResult]) -> float:
    """Compute an overall score as the mean of all metric values."""
    if not eval_results:
        return 0.0
    values = [
        r.metric_value
        for r in eval_results
        if isinstance(r.metric_value, (int, float)) and r.metric_name != "query_error"
    ]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


# ---------------------------------------------------------------------------
# Status reporting helpers
# ---------------------------------------------------------------------------


def _report(
    callbacks: JobCallbacks,
    status: JobStatus,
    phase: JobPhase,
    progress: float,
    message: str,
) -> None:
    """Send a progress update to EvalHub."""
    callbacks.report_status(
        JobStatusUpdate(
            status=status,
            phase=phase,
            progress=progress,
            message=MessageInfo(message=message, message_code=phase.value),
        )
    )


def _report_fatal(
    callbacks: JobCallbacks,
    error_message: str,
    phase: JobPhase = JobPhase.RUNNING_EVALUATION,
) -> None:
    """Report a fatal error to EvalHub."""
    callbacks.report_status(
        JobStatusUpdate(
            status=JobStatus.FAILED,
            phase=phase,
            error=ErrorInfo(message=error_message, message_code="evaluation_failed"),
            message=MessageInfo(message=error_message, message_code="error"),
        )
    )


# ---------------------------------------------------------------------------
# MLflow results logging
# ---------------------------------------------------------------------------


def _log_mlflow_run(
    tracking_uri: str,
    experiment_name: str,
    config: JobSpec,
    eval_results: list[EvaluationResult],
    overall_score: float,
    duration: float,
    num_queries: int,
) -> str | None:
    """Log eval results to MLflow as a run with metrics and params."""
    try:
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)

        run_name = f"{config.model.name}-{config.benchmark_id}"
        with mlflow.start_run(run_name=run_name) as run:
            mlflow.set_tag("agent", config.model.name)
            mlflow.set_tag("agent_url", config.model.url)
            mlflow.set_tag("benchmark", config.benchmark_id)
            mlflow.set_tag("evalhub_job_id", config.id)

            mlflow.log_param("benchmark_id", config.benchmark_id)
            mlflow.log_param("model_name", config.model.name)
            mlflow.log_param("agent_url", config.model.url)
            mlflow.log_param("job_id", config.id)
            mlflow.log_param("num_queries", num_queries)

            for result in eval_results:
                if isinstance(result.metric_value, (int, float)):
                    mlflow.log_metric(result.metric_name, result.metric_value)
                    pass_rate = (result.metadata or {}).get("pass_rate")
                    if pass_rate is not None:
                        mlflow.log_metric(f"{result.metric_name}_pass_rate", pass_rate)

            mlflow.log_metric("overall_score", overall_score)
            mlflow.log_metric("duration_seconds", duration)

        logger.info(
            "MLflow run logged to experiment '%s' (run_id=%s)",
            experiment_name,
            run.info.run_id,
        )
        return run.info.run_id
    except Exception:
        logger.exception("Failed to log MLflow run")
        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the agentic-eval-adapter.

    Uses AdapterSettings to load env-based config and JobSpec from
    /meta/job.json (on-cluster) or EVALHUB_JOB_SPEC_PATH (dev).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        settings = AdapterSettings.from_env()
        adapter = AgenticEvalAdapter(settings=settings)
        job_spec = adapter.job_spec

        callbacks = DefaultCallbacks(
            job_id=job_spec.id,
            benchmark_id=job_spec.benchmark_id,
            benchmark_index=job_spec.benchmark_index,
            provider_id=job_spec.provider_id,
            sidecar_url=job_spec.callback_url,
        )

        logger.info(
            "Starting agentic eval: benchmark=%s model=%s url=%s",
            job_spec.benchmark_id,
            job_spec.model.name,
            job_spec.model.url,
        )

        results = adapter.run_benchmark_job(job_spec, callbacks)

        logger.info(
            "Eval complete: overall_score=%.4f examples=%d duration=%.1fs",
            results.overall_score or 0.0,
            results.num_examples_evaluated,
            results.duration_seconds,
        )
    except Exception:
        logger.exception("Adapter failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
