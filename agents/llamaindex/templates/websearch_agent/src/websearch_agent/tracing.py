import logging
import time
from os import getenv
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger("tracing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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
            response = requests.get(mlflow_url, timeout=min(5, remaining))
            if response.status_code == 200:
                logger.info(
                    f"MLflow health check passed at {mlflow_url} with status code {response.status_code}."
                )
                return  # Success, exit the function without error
            else:
                logger.warning(
                    f"MLflow returned status code {response.status_code} at {mlflow_url}\n"
                    f"  Status Code: {response.status_code}\n"
                    f"  Reason: {response.reason}"
                )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to connect to MLflow at {mlflow_url}: {e}")

        logger.warning(f"Retrying in {retry_interval} seconds...")
        time.sleep(retry_interval)


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
    load_dotenv()
    tracking_uri: Optional[str] = getenv("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        logger.info("[Tracing] MLFLOW_TRACKING_URI not set. Tracing is disabled.")
        return

    try:
        import mlflow
        import mlflow.llama_index
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
        logger.info(f"[Tracing] MLflow server is reachable at {tracking_uri}")
    except RuntimeError as e:
        logger.warning(
            f"[Tracing] MLflow server is unreachable at {tracking_uri}. "
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

        mlflow.llama_index.autolog()

        logger.info(
            f"[Tracing Enabled] MLflow -> {tracking_uri}, Experiment: {experiment_name}"
        )
    except Exception as e:
        logger.warning(
            f"[Tracing] Failed to configure MLflow tracing at {tracking_uri}. "
            f"Continuing without tracing. Error: {e}"
        )
