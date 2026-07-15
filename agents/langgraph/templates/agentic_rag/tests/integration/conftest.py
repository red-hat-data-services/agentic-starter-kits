from __future__ import annotations

import logging
import os

import integration.conftest  # noqa: F401 — re-exports cluster_auth, repo_root
import pytest
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

# Optional per agent.yaml but required here to ensure RAG-capable deployment.
_REQUIRED_ENV = ("BASE_URL", "MODEL_ID", "EMBEDDING_MODEL", "VECTOR_STORE_ID")


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_env_file(agent_dir, container_image):
    """Write a .env file with both base and RAG-specific env vars."""
    missing = [v for v in _REQUIRED_ENV if v not in os.environ]
    if missing:
        pytest.fail(
            f"Missing required env vars for tier-2 RAG agent: {', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )

    raw_dim = os.environ.get("EMBEDDING_DIMENSION", "768")
    try:
        embedding_dim = int(raw_dim)
    except ValueError:
        pytest.fail(f"EMBEDDING_DIMENSION must be an integer, got: {raw_dim!r}")

    env_path = agent_dir / ".env"
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={os.environ['BASE_URL']}\n"
        f"MODEL_ID={os.environ['MODEL_ID']}\n"
        f"CONTAINER_IMAGE={container_image}\n"
        f"EMBEDDING_MODEL={os.environ['EMBEDDING_MODEL']}\n"
        f"EMBEDDING_DIMENSION={embedding_dim}\n"
        f"VECTOR_STORE_ID={os.environ['VECTOR_STORE_ID']}\n"
        f"VECTOR_STORE_PROVIDER={os.environ.get('VECTOR_STORE_PROVIDER', 'milvus')}\n"
    )
    return env_path


@pytest.fixture(scope="module")
def deployed_agent(cluster_auth, agent_dir, agent_name):
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
