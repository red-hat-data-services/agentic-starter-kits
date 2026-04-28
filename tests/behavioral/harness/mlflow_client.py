"""Optional MLflow trace enrichment for eval results.

When an MLflow server is available, this module can query traces to extract
tool calls and token usage that aren't exposed in the HTTP response.

Usage:
    client = MLflowTraceClient("http://localhost:5000", "react-agent-evals")
    # After running an eval, enrich with trace data:
    enriched = client.enrich_eval_result(result, since_ms=request_start_ms)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TraceData:
    """Extracted data from an MLflow trace."""

    tool_calls: list[dict[str, Any]]
    token_usage: dict[str, int | None]
    spans: list[dict[str, Any]]


class MLflowTraceClient:
    """Client for querying MLflow traces after eval runs."""

    def __init__(
        self,
        tracking_uri: str,
        experiment_name: str,
        wait_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        # Configurable via env vars for CI tuning
        self.default_wait_seconds = wait_seconds or float(
            os.environ.get("MLFLOW_TRACE_WAIT_SECONDS", "2.0")
        )
        self.default_max_retries = max_retries or int(
            os.environ.get("MLFLOW_TRACE_MAX_RETRIES", "3")
        )
        self._client = None
        self._experiment_id = None

    def _get_client(self):
        """Lazy-init the MLflow client."""
        if self._client is None:
            import mlflow

            mlflow.set_tracking_uri(self.tracking_uri)
            self._client = mlflow.MlflowClient(self.tracking_uri)

            # Look up experiment ID
            experiment = self._client.get_experiment_by_name(self.experiment_name)
            if experiment:
                self._experiment_id = experiment.experiment_id
            else:
                logger.warning(
                    f"MLflow experiment '{self.experiment_name}' not found"
                )
        return self._client

    def get_latest_trace(
        self,
        since_ms: int | None = None,
        wait_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> TraceData | None:
        """Get the most recent trace from the experiment.

        Args:
            since_ms: Only return traces created after this timestamp (ms).
                      Prevents picking up stale traces from previous requests.
            wait_seconds: Seconds to wait between retries (traces are async).
            max_retries: Number of retry attempts.
        """
        import mlflow

        wait_seconds = wait_seconds if wait_seconds is not None else self.default_wait_seconds
        max_retries = max_retries if max_retries is not None else self.default_max_retries

        client = self._get_client()
        if self._experiment_id is None:
            return None

        for attempt in range(max_retries):
            try:
                traces = mlflow.search_traces(
                    experiment_ids=[self._experiment_id],
                    max_results=1,
                    order_by=["timestamp_ms DESC"],
                )
                if traces is not None and len(traces) > 0:
                    trace_row = traces.iloc[0]
                    trace_id = trace_row["trace_id"]

                    # Skip stale traces from before our request
                    if since_ms is not None:
                        raw_ts = trace_row.get("request_time") or trace_row.get("timestamp_ms")
                        try:
                            request_time = int(raw_ts) if raw_ts is not None else None
                        except (TypeError, ValueError):
                            request_time = None
                        if request_time is not None and request_time < since_ms:
                            # Trace is from before our request, wait for new one
                            if attempt < max_retries - 1:
                                time.sleep(wait_seconds)
                                continue
                            logger.warning(
                                "MLflow trace enrichment failed: no trace found after "
                                f"{max_retries} retries ({wait_seconds}s apart). "
                                "The agent may not have tracing enabled, or async "
                                "logging is slower than expected. Set "
                                "MLFLOW_TRACE_WAIT_SECONDS / MLFLOW_TRACE_MAX_RETRIES "
                                "to tune."
                            )
                            return None

                    if trace_id:
                        return self._extract_trace_data(client, trace_id)
            except Exception as e:
                logger.warning(f"MLflow trace query attempt {attempt + 1}/{max_retries} failed: {e}")

            if attempt < max_retries - 1:
                time.sleep(wait_seconds)

        logger.warning(
            "MLflow trace enrichment failed: no trace found after "
            f"{max_retries} retries ({wait_seconds}s apart). "
            "The agent may not have tracing enabled, or the experiment "
            f"'{self.experiment_name}' has no traces."
        )
        return None

    def _extract_trace_data(
        self, client, request_id: str
    ) -> TraceData | None:
        """Extract tool calls and token usage from a trace's spans."""
        try:
            trace = client.get_trace(request_id)
        except Exception as e:
            logger.warning(f"MLflow: failed to fetch trace {request_id}: {e}")
            return None

        if not trace or not hasattr(trace, "data") or not trace.data:
            return None

        spans = trace.data.spans if hasattr(trace.data, "spans") else []
        tool_calls: list[dict[str, Any]] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        span_summaries: list[dict[str, Any]] = []

        for span in spans:
            span_type = getattr(span, "span_type", None) or ""
            span_name = getattr(span, "name", "")

            span_summaries.append(
                {"name": span_name, "type": str(span_type)}
            )

            # Extract tool calls from TOOL-type spans
            if "TOOL" in str(span_type).upper():
                inputs = getattr(span, "inputs", None)
                tool_call = {"name": span_name}
                if inputs:
                    # Inputs may be a dict or string
                    if isinstance(inputs, dict):
                        tool_call["arguments"] = inputs
                    else:
                        tool_call["arguments"] = {"_raw": str(inputs)}
                else:
                    tool_call["arguments"] = {}

                outputs = getattr(span, "outputs", None)
                if outputs:
                    tool_call["output"] = (
                        str(outputs) if not isinstance(outputs, str) else outputs
                    )

                tool_calls.append(tool_call)

            # Extract token usage from CHAT_MODEL-type spans
            if "CHAT_MODEL" in str(span_type).upper():
                attrs = getattr(span, "attributes", {}) or {}
                # MLflow langchain autolog stores usage as mlflow.chat.tokenUsage
                usage = attrs.get("mlflow.chat.tokenUsage", {})
                if isinstance(usage, dict):
                    total_prompt_tokens += usage.get("input_tokens", 0) or 0
                    total_completion_tokens += (
                        usage.get("output_tokens", 0) or 0
                    )

        token_usage = {
            "prompt_tokens": total_prompt_tokens or None,
            "completion_tokens": total_completion_tokens or None,
            "total_tokens": (
                (total_prompt_tokens + total_completion_tokens)
                if (total_prompt_tokens or total_completion_tokens)
                else None
            ),
        }

        return TraceData(
            tool_calls=tool_calls,
            token_usage=token_usage,
            spans=span_summaries,
        )

    def enrich_eval_result(
        self, result, since_ms: int | None = None, wait_seconds: float | None = None
    ):
        """Enrich an TaskResult with MLflow trace data.

        If tool_calls or tokens_used are missing from the HTTP response,
        fills them in from the MLflow trace.

        Args:
            since_ms: Only use traces created after this timestamp (ms).
            wait_seconds: Seconds to wait between retries.

        Mutates and returns the result.
        """
        trace_data = self.get_latest_trace(
            since_ms=since_ms, wait_seconds=wait_seconds
        )
        if trace_data is None:
            return result

        # Fill in tool calls if HTTP response didn't have them
        if not result.tool_calls and trace_data.tool_calls:
            result.tool_calls = trace_data.tool_calls

        # Fill in token usage if HTTP response didn't have it
        if result.tokens_used is None and trace_data.token_usage.get("total_tokens"):
            result.tokens_used = trace_data.token_usage["total_tokens"]

        # Store trace data in raw_response for downstream scorers
        if isinstance(result.raw_response, dict):
            result.raw_response["_mlflow_trace"] = {
                "tool_calls": trace_data.tool_calls,
                "token_usage": trace_data.token_usage,
                "spans": trace_data.spans,
            }

        return result
