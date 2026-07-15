from __future__ import annotations

import logging
import os

import pytest
from integration.conftest import cluster_auth, repo_root  # noqa: F401
from integration.utils import (
    MakeTargetError,
    RouteNotFoundError,
    get_route,
    load_agent_name,
    resolve_agent_dir,
    run_make,
)

logger = logging.getLogger(__name__)

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"

_REQUIRED_ENV = ("BASE_URL", "MODEL_ID", "MCP_SERVER_URL")


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_env_file(agent_dir, container_image):
    """Write a .env file with base and MCP-specific env vars."""
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        pytest.fail(
            f"Missing required env vars for MCP-backed agent: {', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )
    env_path = agent_dir / ".env"
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={os.environ['BASE_URL']}\n"
        f"MODEL_ID={os.environ['MODEL_ID']}\n"
        f"CONTAINER_IMAGE={container_image}\n"
        f"MCP_SERVER_URL={os.environ['MCP_SERVER_URL']}\n",
        encoding="utf-8",
    )
    return env_path


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, agent_dir, agent_name):  # noqa: F811
    namespace = cluster_auth["namespace"]
    container_image = f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"
    env_path = _write_env_file(agent_dir, container_image)

    deploy_attempted = False
    try:
        try:
            logger.info("Building image on cluster via build-openshift...")
            run_make("build-openshift", cwd=agent_dir, timeout=600)

            logger.info("Deploying to cluster...")
            deploy_attempted = True
            run_make("deploy", cwd=agent_dir, timeout=300)

            route_url = get_route(agent_name, namespace=namespace)
            logger.info("Agent deployed at %s", route_url)
        except (MakeTargetError, RouteNotFoundError) as exc:
            pytest.fail(f"Deployment failed: {exc}")
        except Exception as exc:
            pytest.fail(f"Unexpected error during deployment setup: {exc}")

        yield route_url

    finally:
        if deploy_attempted:
            logger.info("Tearing down deployment...")
            try:
                run_make("undeploy", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Cleanup failed — manual undeploy may be needed", exc_info=True
                )
        env_path.unlink(missing_ok=True)
