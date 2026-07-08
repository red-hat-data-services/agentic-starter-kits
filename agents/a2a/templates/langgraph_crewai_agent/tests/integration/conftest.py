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

_REQUIRED_ENV = ("BASE_URL", "MODEL_ID", "CONTAINER_IMAGE")

_DEPLOYMENT_NAMES = ["a2a-crew-agent", "a2a-langgraph-agent"]

_discovered_routes = {}


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_env_file(agent_dir):
    """Write a .env from env vars. CONTAINER_IMAGE comes from environment (external registry)."""
    missing = [v for v in _REQUIRED_ENV if v not in os.environ]
    if missing:
        pytest.fail(
            f"Missing required env vars for A2A multi-agent deployment: "
            f"{', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )
    env_path = agent_dir / ".env"
    env_path.touch(mode=0o600)
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={os.environ['BASE_URL']}\n"
        f"MODEL_ID={os.environ['MODEL_ID']}\n"
        f"CONTAINER_IMAGE={os.environ['CONTAINER_IMAGE']}\n",
        encoding="utf-8",
    )
    return env_path


@pytest.fixture(scope="module")
def all_routes(deployed_agent):
    """Routes for all deployments, populated by deployed_agent fixture."""
    return _discovered_routes


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, agent_dir, agent_name):  # noqa: F811
    namespace = cluster_auth["namespace"]
    env_path = _write_env_file(agent_dir)

    deployed = False
    try:
        try:
            logger.info("Building container image locally...")
            run_make("build", cwd=agent_dir, timeout=600)

            logger.info("Pushing image to external registry...")
            run_make("push", cwd=agent_dir, timeout=300)

            logger.info("Deploying to cluster (two-phase Helm)...")
            run_make("deploy", cwd=agent_dir, timeout=600)
            deployed = True

            for deploy_name in _DEPLOYMENT_NAMES:
                _discovered_routes[deploy_name] = get_route(
                    deploy_name, namespace=namespace
                )
                logger.info(
                    "Deployment %s at %s",
                    deploy_name,
                    _discovered_routes[deploy_name],
                )

            primary = next(iter(_discovered_routes.values()))
        except (MakeTargetError, RouteNotFoundError) as exc:
            pytest.fail(f"Deployment failed: {exc}")
        except Exception as exc:
            pytest.fail(f"Deployment failed — {exc}")

        yield primary

    finally:
        if deployed:
            logger.info("Tearing down deployment...")
            try:
                run_make("undeploy", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Cleanup failed — manual undeploy may be needed",
                    exc_info=True,
                )
        env_path.unlink(missing_ok=True)
