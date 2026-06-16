import logging
import time
from os import getenv
from typing import Callable, Literal, Optional

from dotenv import load_dotenv

_TRACING_ENABLED: bool = False

logger = logging.getLogger("tracing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _safe_uri(uri: str) -> str:
    """Strip credentials and query params from a URI for safe logging."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(uri)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def check_mlflow_health(
    mlflow_tracking_uri: str, max_wait_time: int = 5, retry_interval: int = 1
) -> None:
    """
    Check MLflow health by trying the /health endpoint. If it fails, retry for a certain duration before giving up.
    args:
        mlflow_tracking_uri: base URI of the MLflow server
        max_wait_time: total time to keep retrying before giving up (in seconds)
        retry_interval: time to wait between retries (in seconds)
    """
    import requests

    mlflow_health_endpoint = "/health"
    mlflow_url = f"{mlflow_tracking_uri.rstrip('/')}{mlflow_health_endpoint}"
    safe_url = _safe_uri(mlflow_url)
    insecure = getenv("MLFLOW_TRACKING_INSECURE_TLS", "").lower() in (
        "true",
        "1",
        "yes",
    )
    start_time = time.time()

    while True:
        remaining = max_wait_time - (time.time() - start_time)
        if remaining <= 0:
            logger.error(
                f"MLflow server is unavailable after {max_wait_time} seconds of checking."
            )
            raise RuntimeError(
                "MLflow server is unavailable. Please start the server or check the URI."
            )

        try:
            response = requests.get(
                mlflow_url, timeout=min(5, remaining), verify=not insecure
            )
            if response.status_code == 200:
                logger.info(
                    f"MLflow health check passed at {safe_url} with status code {response.status_code}."
                )
                return
            else:
                logger.warning(
                    f"MLflow returned status code {response.status_code} at {safe_url}\n"
                    f"  Status Code: {response.status_code}\n"
                    f"  Reason: {response.reason}"
                )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to connect to MLflow at {safe_url}: {e}")

        logger.warning(f"Retrying in {retry_interval} seconds...")
        time.sleep(retry_interval)


def wrap_func_with_mlflow_trace(
    func: Callable, span_type: Literal["tool", "agent"], name: Optional[str] = None
) -> Callable:
    """
    Wrap a function with MLflow.trace(span_type=SpanType.<type>) if MLflow is enabled.

    Returns the original function if MLflow is not installed or tracing is disabled.
    """
    if not _TRACING_ENABLED:
        return func

    import mlflow
    from mlflow.entities import SpanType

    if span_type == "tool":
        return mlflow.trace(span_type=SpanType.TOOL, name=name)(func)
    elif span_type == "agent":
        return mlflow.trace(span_type=SpanType.AGENT, name=name)(func)
    else:
        raise ValueError(f"Unsupported trace type: {span_type}")


def enable_tracing() -> None:
    """
    Enable MLflow tracing if MLFLOW_TRACKING_URI is set.

    Behavior:
    1. If MLFLOW_TRACKING_URI is not set: tracing is skipped.
    2. If MLFLOW_TRACKING_URI is set:
       - Try to connect to the server.
       - If the server is reachable: tracing is enabled.
       - If the server is unreachable: log a warning and continue without tracing.
    """
    global _TRACING_ENABLED
    load_dotenv()
    tracking_uri: Optional[str] = getenv("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        logger.info("[Tracing] MLFLOW_TRACKING_URI not set. Tracing is disabled.")
        return

    try:
        import mlflow
        import mlflow.litellm
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "MLFLOW_TRACKING_URI is set but mlflow is not installed. "
            "Install it with: uv sync --extra tracing"
        ) from e

    # Check if server is reachable
    try:
        try:
            health_check_timeout = int(getenv("MLFLOW_HEALTH_CHECK_TIMEOUT", "5"))
        except ValueError:
            health_check_timeout = 5
        check_mlflow_health(
            mlflow_tracking_uri=tracking_uri, max_wait_time=health_check_timeout
        )
        safe_uri = _safe_uri(tracking_uri)
        logger.info(f"[Tracing] MLflow server is reachable at {safe_uri}")
    except RuntimeError as e:
        safe_uri = _safe_uri(tracking_uri)
        logger.warning(
            f"[Tracing] MLflow server is unreachable at {safe_uri}. "
            f"Tried connecting for {health_check_timeout}s. Continuing without tracing. Error: {e}"
        )
        return

    # Server is reachable → enable tracing
    try:
        mlflow.set_tracking_uri(tracking_uri)
        experiment_name: str = getenv(
            "MLFLOW_EXPERIMENT_NAME", "default-agent-experiment"
        )
        mlflow.set_experiment(experiment_name)
        mlflow.config.enable_async_logging()

        # LiteLLM autolog captures CHAT_MODEL spans for LLM calls.
        # Google ADK routes all inference through LiteLLM's OpenAI provider.
        mlflow.litellm.autolog()

        _TRACING_ENABLED = True
        logger.info(
            f"[Tracing Enabled] MLflow -> {_safe_uri(tracking_uri)}, Experiment: {experiment_name}"
        )
    except Exception as e:
        logger.warning(
            f"[Tracing] Failed to configure MLflow tracing at {_safe_uri(tracking_uri)}. "
            f"Continuing without tracing. Error: {e}"
        )
