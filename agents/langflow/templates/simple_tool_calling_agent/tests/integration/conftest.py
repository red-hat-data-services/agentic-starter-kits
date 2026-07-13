from __future__ import annotations

import logging

import pytest
from integration.conftest import cluster_auth, repo_root  # noqa: F401
from integration.utils import (
    RouteNotFoundError,
    get_route,
    load_agent_name,
    resolve_agent_dir,
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, agent_name):  # noqa: F811
    namespace = cluster_auth["namespace"]
    try:
        route_url = get_route(agent_name, namespace=namespace)
    except RouteNotFoundError as exc:
        pytest.fail(
            f"Pre-deployed agent route not found: {exc}. "
            "Ensure the agent is deployed before running integration tests."
        )
    logger.info("Pre-deployed agent at %s", route_url)
    yield route_url
