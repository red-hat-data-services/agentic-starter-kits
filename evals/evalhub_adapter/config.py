"""Configuration translation between EvalHub JobSpec and our TaskConfig."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args
from urllib.parse import urlparse

from harness.runner import TaskConfig

logger = logging.getLogger(__name__)

ApiFormat = Literal["chat_completions", "langflow_run"]
_VALID_API_FORMATS = get_args(ApiFormat)

_ALLOWED_URL_SCHEMES = {"https", "http"}
_BLOCKED_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
}


def _validate_url(url: str, label: str) -> None:
    """Validate a URL and warn about insecure schemes.

    Rejects non-HTTP(S) schemes entirely (e.g. file://, ftp://) and logs
    a warning for plain HTTP which is vulnerable to eavesdropping.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"{label} has unsupported scheme '{parsed.scheme}'. "
            f"Only {_ALLOWED_URL_SCHEMES} are allowed."
        )
    if not parsed.netloc:
        raise ValueError(f"{label} has no host component: '{url}'")
    hostname = parsed.hostname or ""
    if hostname in _BLOCKED_HOSTS or hostname.startswith("169.254."):
        import os

        is_localhost = hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
        if (
            is_localhost
            and os.environ.get("EVALHUB_ALLOW_LOCALHOST", "").lower() == "true"
        ):
            logger.warning(
                "%s targets '%s' — allowed via EVALHUB_ALLOW_LOCALHOST. "
                "Do not use in production.",
                label,
                hostname,
            )
        else:
            raise ValueError(
                f"{label} targets a blocked host '{hostname}'. "
                "Cloud metadata endpoints and localhost are not allowed."
            )
    if parsed.scheme == "http":
        logger.warning(
            "%s uses plain HTTP (%s) — traffic is unencrypted and "
            "vulnerable to eavesdropping. Use HTTPS in production.",
            label,
            url,
        )


@dataclass
class AgenticEvalParams:
    """Parameters parsed from JobSpec.parameters.

    These are agent-specific settings passed by the EvalHub job submitter,
    NOT baked into benchmark definitions. Benchmark definitions (scorer lists)
    are agent-agnostic, but query files contain agent-specific expected_tools.
    Only known_tools (for hallucination detection), thresholds, and forbidden
    actions come from job parameters.

    Example job submission parameters:
        {
            "known_tools": ["search"],
            "forbidden_actions": ["shell execution"],
            "max_latency_seconds": 8.0,
            "timeout_seconds": 30.0
        }
    """

    # Agent-specific
    known_tools: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)

    # Thresholds
    max_latency_seconds: float = 10.0

    # Execution
    timeout_seconds: float = 30.0
    verify_ssl: bool = True
    fixtures_path: str = "fixtures"
    stream: bool = False
    api_format: ApiFormat = "chat_completions"
    flow_id: str | None = None

    # MLflow trace enrichment (reads tool calls from agent-side traces)
    mlflow_tracking_uri: str | None = None
    mlflow_experiment_name: str | None = None
    # Agent-side experiment for trace lookups (defaults to mlflow_experiment_name)
    mlflow_trace_experiment_name: str | None = None

    def __post_init__(self) -> None:
        """Validate fields and apply defaults after dataclass init."""
        if self.api_format not in _VALID_API_FORMATS:
            raise ValueError(
                f"api_format must be one of {_VALID_API_FORMATS}, "
                f"got '{self.api_format}'"
            )
        if self.api_format == "langflow_run" and not self.flow_id:
            raise ValueError("flow_id is required when api_format is 'langflow_run'")
        if self.flow_id and not re.fullmatch(r"[a-zA-Z0-9_-]+", self.flow_id):
            raise ValueError(
                f"flow_id must contain only alphanumeric characters, hyphens, "
                f"and underscores — got '{self.flow_id}'"
            )
        if not self.mlflow_trace_experiment_name:
            self.mlflow_trace_experiment_name = self.mlflow_experiment_name
        if not isinstance(self.timeout_seconds, (int, float)):
            raise TypeError(
                f"timeout_seconds must be numeric, got {type(self.timeout_seconds).__name__}"
            )
        if not isinstance(self.max_latency_seconds, (int, float)):
            raise TypeError(
                f"max_latency_seconds must be numeric, got {type(self.max_latency_seconds).__name__}"
            )
        if not isinstance(self.known_tools, list):
            raise TypeError(
                f"known_tools must be a list, got {type(self.known_tools).__name__}"
            )
        if not isinstance(self.forbidden_actions, list):
            raise TypeError(
                f"forbidden_actions must be a list, got {type(self.forbidden_actions).__name__}"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be positive, got {self.timeout_seconds}"
            )
        if self.max_latency_seconds <= 0:
            raise ValueError(
                f"max_latency_seconds must be positive, got {self.max_latency_seconds}"
            )
        if not self.mlflow_tracking_uri or not self.mlflow_experiment_name:
            raise ValueError(
                "mlflow_tracking_uri and mlflow_experiment_name are required. "
                "EvalHub runs must log results to MLflow."
            )
        _validate_url(self.mlflow_tracking_uri, "mlflow_tracking_uri")
        if ".." in Path(self.fixtures_path).parts:
            raise ValueError(
                "fixtures_path must not contain '..' components — "
                f"got '{self.fixtures_path}'"
            )
        if not self.verify_ssl:
            import os

            if os.environ.get("EVALHUB_ALLOW_INSECURE_TLS", "").lower() != "true":
                raise ValueError(
                    "verify_ssl=False requires EVALHUB_ALLOW_INSECURE_TLS=true "
                    "in the environment. Disabling TLS verification makes "
                    "connections vulnerable to MITM attacks."
                )
            logger.error(
                "TLS verification disabled (verify_ssl=False) — "
                "connections are vulnerable to MITM attacks. "
                "Only use this for development/testing."
            )

    @classmethod
    def from_dict(cls, params: dict[str, Any]) -> AgenticEvalParams:
        """Create from a dict, ignoring unknown keys."""
        known_fields = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in params.items() if k in known_fields}
        dropped = set(params) - known_fields
        if dropped:
            logger.info("AgenticEvalParams: ignoring unknown keys: %s", sorted(dropped))
        return cls(**filtered)


def job_spec_to_task_config(
    agent_url: str,
    query: str,
    expected_tools: list[str] | None,
    params: AgenticEvalParams,
    model_name: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> TaskConfig:
    """Translate EvalHub job parameters into our TaskConfig."""
    _validate_url(agent_url, "agent_url")
    stream = False if params.api_format == "langflow_run" else params.stream
    return TaskConfig(
        agent_url=agent_url,
        query=query,
        expected_tools=expected_tools,
        timeout_seconds=params.timeout_seconds,
        model=model_name,
        stream=stream,
        api_format=params.api_format,
        flow_id=params.flow_id,
        extra_headers=extra_headers or {},
    )
