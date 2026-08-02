"""Re-export shared cluster fixtures from the repo-root integration harness.

Import explicitly from ``tests/integration/conftest.py`` so this agent's local
``tests/integration/`` package cannot shadow the shared ``integration``
namespace when pytest collects tests from here.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

import pytest
from integration.utils import (
    MakeTargetError,
    RouteNotFoundError,
    get_guardrails_route,
    get_guardrails_service_url,
    run_make,
    wait_for_guardrails_ready,
)

_SHARED_INTEGRATION_CONFTEST = (
    Path(__file__).resolve().parents[6] / "tests" / "integration" / "conftest.py"
)
_spec = importlib.util.spec_from_file_location(
    "repo_integration_conftest",
    _SHARED_INTEGRATION_CONFTEST,
)
if _spec is None or _spec.loader is None:
    raise ImportError(
        f"Cannot load shared integration conftest at {_SHARED_INTEGRATION_CONFTEST}"
    )
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

cluster_auth = _mod.cluster_auth
repo_root = _mod.repo_root

logger = logging.getLogger(__name__)
GUARDRAILS_CR_NAME = "langgraph-guardrailed-agent-guardrails"
_AGENT_DIR = Path(__file__).resolve().parents[2]


def _ensure_cluster_env(agent_dir: Path) -> None:
    """Write cluster.env from example + NVIDIA_API_KEY when missing."""
    env_dir = agent_dir / "deploy" / "overlays" / "ci-testing"
    cluster_env = env_dir / "cluster.env"
    if cluster_env.is_file():
        return
    example = env_dir / "cluster.env.example"
    nvidia_api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not nvidia_api_key:
        return
    text = example.read_text(encoding="utf-8")
    text = text.replace("NVIDIA_API_KEY=replace-me", f"NVIDIA_API_KEY={nvidia_api_key}")
    cluster_env.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def deployed_guardrails(cluster_auth):
    """Deploy NemoGuardrails CR (nemoguard profile) before integration tests."""
    namespace = cluster_auth["namespace"]
    agent_dir = _AGENT_DIR
    if not os.environ.get("NVIDIA_API_KEY"):
        pytest.skip("NVIDIA_API_KEY not set — required for nemoguard cluster deploy")

    _ensure_cluster_env(agent_dir)
    deployed = False
    try:
        logger.info("Deploying NeMo Guardrails (nemoguard profile)...")
        run_make("deploy-guardrails", cwd=agent_dir, timeout=600)
        deployed = True
        wait_for_guardrails_ready(GUARDRAILS_CR_NAME, namespace)
        service_url = get_guardrails_service_url(GUARDRAILS_CR_NAME, namespace)
        logger.info("Guardrails service URL: %s", service_url)
        yield service_url
    except (MakeTargetError, RuntimeError) as exc:
        pytest.fail(f"Guardrails deployment failed: {exc}")
    finally:
        if deployed:
            logger.info("Tearing down guardrails...")
            try:
                run_make("undeploy-guardrails", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Guardrails cleanup failed — manual undeploy may be needed",
                    exc_info=True,
                )


@pytest.fixture(scope="module")
def guardrails_integration_url(cluster_auth, deployed_guardrails):
    """External or in-cluster URL for direct guardrails behavior tests."""
    namespace = cluster_auth["namespace"]
    if url := os.environ.get("GUARDRAILS_INTEGRATION_URL"):
        return url.rstrip("/")
    try:
        return get_guardrails_route(GUARDRAILS_CR_NAME, namespace=namespace).rstrip("/")
    except RouteNotFoundError:
        return deployed_guardrails.removesuffix("/v1")


__all__ = [
    "cluster_auth",
    "repo_root",
    "deployed_guardrails",
    "guardrails_integration_url",
    "GUARDRAILS_CR_NAME",
]
