from __future__ import annotations

import logging
import os
import shlex

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

# Keep in sync with agent.yaml env.required / env.optional and SummarizerConfig.from_env().
_REQUIRED_ENV = (
    "BASE_URL",
    "MODEL_ID",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "GITHUB_REPOSITORY",
)

# Optional agent env vars forwarded when present (secrets stay out of logs).
_OPTIONAL_ENV = (
    "GITHUB_WORKFLOW",
    "GITHUB_WORKFLOW_FILE",
    "GITHUB_TOKEN",
    "SLACK_WEBHOOK_URL",
)

_DEFAULTS = {
    "GITHUB_WORKFLOW": "QG4: Agent Deployment Integration Tests",
    "GITHUB_WORKFLOW_FILE": "agent-deployment-test.yaml",
}


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_env_file(agent_dir, container_image):
    """Write a .env file with base and PostgreSQL env vars."""
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        pytest.fail(
            f"Missing required env vars for database-backed agent: {', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )
    env_path = agent_dir / ".env"
    def shell_assign(name: str, value: str) -> str:
        return f"{name}={shlex.quote(value)}"

    lines = [
        shell_assign("API_KEY", os.environ.get("API_KEY", "not-needed")),
        shell_assign("BASE_URL", os.environ["BASE_URL"]),
        shell_assign("MODEL_ID", os.environ["MODEL_ID"]),
        shell_assign("CONTAINER_IMAGE", container_image),
        shell_assign("POSTGRES_HOST", os.environ["POSTGRES_HOST"]),
        shell_assign("POSTGRES_PORT", os.environ["POSTGRES_PORT"]),
        shell_assign("POSTGRES_DB", os.environ["POSTGRES_DB"]),
        shell_assign("POSTGRES_USER", os.environ["POSTGRES_USER"]),
        shell_assign("POSTGRES_PASSWORD", os.environ["POSTGRES_PASSWORD"]),
        shell_assign("GITHUB_REPOSITORY", os.environ["GITHUB_REPOSITORY"]),
    ]
    for var in _OPTIONAL_ENV:
        value = os.environ.get(var) or _DEFAULTS.get(var)
        if value:
            lines.append(shell_assign(var, value))
    env_path.write_text("\n".join(lines) + "\n")
    return env_path


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, agent_dir, agent_name):  # noqa: F811
    namespace = cluster_auth["namespace"]
    container_image = f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"
    env_path = _write_env_file(agent_dir, container_image)

    deployed = False
    try:
        try:
            logger.info("Building image on cluster via build-openshift...")
            run_make("build-openshift", cwd=agent_dir, timeout=600)

            logger.info("Deploying to cluster...")
            run_make("deploy", cwd=agent_dir, timeout=300)
            deployed = True

            route_url = get_route(agent_name, namespace=namespace)
            logger.info("Agent deployed at %s", route_url)
        except (MakeTargetError, RouteNotFoundError) as exc:
            pytest.fail(f"Deployment failed: {exc}")
        except Exception as exc:
            pytest.fail(f"Unexpected error during deployment setup: {exc}")

        yield route_url

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
