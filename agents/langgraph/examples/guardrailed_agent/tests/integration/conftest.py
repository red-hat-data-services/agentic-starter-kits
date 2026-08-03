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
    get_guardrails_service_url,
    get_route,
    run_make,
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


@pytest.fixture(scope="session")
def deployed_guardrails(cluster_auth):
    """Deploy NemoGuardrails CR (nemoguard profile) before integration tests."""
    namespace = cluster_auth["namespace"]
    if not os.environ.get("NVIDIA_API_KEY"):
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(
                "NVIDIA_API_KEY not set — QG4 guardrails deploy must fail fast in CI"
            )
        pytest.skip("NVIDIA_API_KEY not set — required for nemoguard cluster deploy")

    deployed = False
    try:
        logger.info("Deploying NeMo Guardrails (nemoguard profile)...")
        run_make("deploy-guardrails", cwd=_AGENT_DIR, timeout=600)
        deployed = True
        service_url = get_guardrails_service_url(GUARDRAILS_CR_NAME, namespace)
        logger.info("Guardrails service URL: %s", service_url)
        yield service_url
    except (MakeTargetError, RuntimeError) as exc:
        pytest.fail(f"Guardrails deployment failed: {exc}")
    finally:
        if deployed:
            logger.info("Tearing down guardrails...")
            try:
                run_make("undeploy-guardrails", cwd=_AGENT_DIR, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Guardrails cleanup failed — manual undeploy may be needed",
                    exc_info=True,
                )


@pytest.fixture(scope="session")
def guardrails_integration_url(cluster_auth, deployed_guardrails):
    """External URL for direct guardrails behavior tests.

    Outside-cluster runners need the OpenShift Route. The in-cluster Service
    fallback only works when tests execute from within the cluster network.
    """
    namespace = cluster_auth["namespace"]
    if url := os.environ.get("GUARDRAILS_INTEGRATION_URL"):
        return url.rstrip("/")
    try:
        return get_route(GUARDRAILS_CR_NAME, namespace=namespace).rstrip("/")
    except RouteNotFoundError:
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(
                "Guardrails Route not found — external CI runners cannot reach the "
                "in-cluster Service fallback. Set GUARDRAILS_INTEGRATION_URL or "
                "ensure the NemoGuardrails Route exists."
            )
        return deployed_guardrails.removesuffix("/v1")


__all__ = [
    "cluster_auth",
    "repo_root",
    "deployed_guardrails",
    "guardrails_integration_url",
    "GUARDRAILS_CR_NAME",
]
