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
    run_make,
)

logger = logging.getLogger(__name__)

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"


@pytest.fixture(scope="module")
def agent_dir(repo_root):
    return repo_root / "agents" / "google" / "adk"


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_env_file(agent_dir, container_image):
    """Write a .env file so Makefile targets can source it."""
    missing = [v for v in ("BASE_URL", "MODEL_ID") if v not in os.environ]
    if missing:
        pytest.fail(
            f"Missing required env vars: {', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )
    env_path = agent_dir / ".env"
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={os.environ['BASE_URL']}\n"
        f"MODEL_ID={os.environ['MODEL_ID']}\n"
        f"CONTAINER_IMAGE={container_image}\n"
    )
    return env_path


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, agent_dir, agent_name):
    namespace = cluster_auth["namespace"]
    container_image = f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"
    env_path = _write_env_file(agent_dir, container_image)

    deployed = False
    try:
        logger.info("Building image on cluster via build-openshift...")
        run_make("build-openshift", cwd=agent_dir, timeout=600)

        logger.info("Deploying to cluster...")
        run_make("deploy", cwd=agent_dir, timeout=300)
        deployed = True

        route_url = get_route(agent_name, namespace=namespace)
        logger.info("Agent deployed at %s", route_url)

        yield route_url

    except (MakeTargetError, RouteNotFoundError) as exc:
        pytest.fail(f"Deployment failed: {exc}")

    finally:
        if deployed:
            logger.info("Tearing down deployment...")
            try:
                run_make("undeploy", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Cleanup failed — manual undeploy may be needed", exc_info=True
                )
        env_path.unlink(missing_ok=True)


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    result = health_check(f"{route_url}/health", retries=12, backoff=5.0)

    assert result["status"] == "healthy"
    assert result["agent_initialized"] is True
