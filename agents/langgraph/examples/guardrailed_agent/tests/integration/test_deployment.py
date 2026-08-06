from __future__ import annotations

import logging
import os

import pytest
from integration.utils import (
    MakeTargetError,
    RouteNotFoundError,
    get_route,
    health_check,
    load_agent_name,
    resolve_agent_dir,
    run_make,
)

logger = logging.getLogger(__name__)

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_env_file(agent_dir, container_image, base_url: str, model_id: str):
    """Write a .env file so Makefile targets can source it."""
    env_path = agent_dir / ".env"
    orig_env = None
    if env_path.exists():
        orig_env = env_path.read_text(encoding="utf-8")
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={base_url}\n"
        f"MODEL_ID={model_id}\n"
        f"CONTAINER_IMAGE={container_image}\n",
        encoding="utf-8",
    )
    return env_path, orig_env


def _restore_env_file(env_path, orig_env):
    if orig_env is not None:
        try:
            env_path.write_text(orig_env, encoding="utf-8")
        except Exception:
            logger.exception("Failed to restore pre-existing .env at %s", env_path)
    else:
        env_path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, deployed_guardrails, agent_dir, agent_name):
    namespace = cluster_auth["namespace"]
    container_image = f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"
    model_id = os.environ.get("MODEL_ID", "qwen2-5-7b-instruct")
    base_url = deployed_guardrails

    env_path, orig_env = _write_env_file(
        agent_dir, container_image, base_url=base_url, model_id=model_id
    )

    deployed = False
    try:
        logger.info("Building image on cluster via build-openshift...")
        run_make("build-openshift", cwd=agent_dir, timeout=600)

        logger.info("Deploying agent to cluster...")
        run_make("deploy", cwd=agent_dir, timeout=300)
        deployed = True

        route_url = get_route(agent_name, namespace=namespace)
        logger.info("Agent deployed at %s", route_url)

        yield route_url

    except (MakeTargetError, RouteNotFoundError) as exc:
        pytest.fail(f"Deployment failed: {exc}")

    finally:
        if deployed:
            logger.info("Tearing down agent deployment...")
            try:
                run_make("undeploy", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Agent cleanup failed — manual undeploy may be needed",
                    exc_info=True,
                )
        _restore_env_file(env_path, orig_env)


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    result = health_check(f"{route_url}/health", retries=12, backoff=5.0)

    assert result["status"] == "healthy"
    assert result["agent_initialized"] is True
    assert result["guardrails_reachable"] is True
