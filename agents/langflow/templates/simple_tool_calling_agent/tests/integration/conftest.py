from __future__ import annotations

import logging
import os

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
    # Allow a direct URL override for pre-deployed agents whose route lives
    # in a namespace the CI service account cannot read (e.g. langflow-agent).
    override_url = os.environ.get("DEPLOYED_AGENT_URL", "").strip()
    if override_url:
        logger.info("Using DEPLOYED_AGENT_URL override: %s", override_url)
        yield override_url
        return

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
