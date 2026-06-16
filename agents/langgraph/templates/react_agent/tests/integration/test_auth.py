from __future__ import annotations

import logging
import os

import pytest
from integration.utils import (
    MakeTargetError,
    RouteNotFoundError,
    chat_completion_request,
    create_sa_token,
    create_serviceaccount,
    delete_serviceaccount,
    get_route,
    health_check,
    load_agent_name,
    resolve_agent_dir,
    run_make,
)

logger = logging.getLogger(__name__)

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"
ALLOWED_CALLER_SA = "langgraph-react-agent-caller"
DENIED_CALLER_SA = "langgraph-react-agent-denied"
AUDIENCE = "langgraph-react-agent"
WRONG_AUDIENCE = "langgraph-react-agent-wrong"


@pytest.fixture(scope="module")
def agent_dir():
    return resolve_agent_dir(__file__)


@pytest.fixture(scope="module")
def agent_name(agent_dir):
    return load_agent_name(agent_dir)


def _write_auth_env_file(*, agent_dir, container_image, namespace, allowed_caller_sa):
    missing = [v for v in ("BASE_URL", "MODEL_ID") if v not in os.environ]
    if missing:
        pytest.fail(
            f"Missing required env vars: {', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )
    env_path = agent_dir / ".env"
    orig_env = None
    if env_path.exists():
        orig_env = env_path.read_text(encoding="utf-8")
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={os.environ['BASE_URL']}\n"
        f"MODEL_ID={os.environ['MODEL_ID']}\n"
        f"CONTAINER_IMAGE={container_image}\n"
        "AUTH_ENABLED=true\n"
        f"AUTH_AUDIENCE={AUDIENCE}\n"
        f"AUTH_ALLOWED_SERVICEACCOUNTS={namespace}:{allowed_caller_sa}\n",
        encoding="utf-8",
    )
    return env_path, orig_env


@pytest.fixture(scope="module")
def auth_callers(cluster_auth):
    namespace = cluster_auth["namespace"]
    create_serviceaccount(ALLOWED_CALLER_SA, namespace)
    create_serviceaccount(DENIED_CALLER_SA, namespace)
    try:
        yield {"allowed": ALLOWED_CALLER_SA, "denied": DENIED_CALLER_SA}
    finally:
        delete_serviceaccount(ALLOWED_CALLER_SA, namespace)
        delete_serviceaccount(DENIED_CALLER_SA, namespace)


@pytest.fixture(scope="module")
def deployed_auth_agent(cluster_auth, agent_dir, agent_name, auth_callers):
    namespace = cluster_auth["namespace"]
    container_image = f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"
    env_path, orig_env = _write_auth_env_file(
        agent_dir=agent_dir,
        container_image=container_image,
        namespace=namespace,
        allowed_caller_sa=auth_callers["allowed"],
    )

    deployed = False
    try:
        logger.info("Building image on cluster via build-openshift...")
        run_make("build-openshift", cwd=agent_dir, timeout=1200)

        logger.info("Deploying auth-enabled agent to cluster...")
        run_make("deploy", cwd=agent_dir, timeout=300)
        deployed = True

        route_url = get_route(agent_name, namespace=namespace)
        logger.info("Auth-enabled agent deployed at %s", route_url)
        yield route_url
    except (MakeTargetError, RouteNotFoundError) as exc:
        pytest.fail(f"Auth deployment failed: {exc}")
    finally:
        if deployed:
            logger.info("Tearing down auth deployment...")
            try:
                run_make("undeploy", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Auth cleanup failed — manual undeploy may be needed", exc_info=True
                )
        if orig_env is not None:
            try:
                env_path.write_text(orig_env, encoding="utf-8")
            except Exception:
                logger.exception("Failed to restore pre-existing .env at %s", env_path)
        else:
            env_path.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def auth_headers(cluster_auth, auth_callers):
    namespace = cluster_auth["namespace"]
    allowed = create_sa_token(
        service_account=auth_callers["allowed"],
        namespace=namespace,
        audience=AUDIENCE,
    )
    denied = create_sa_token(
        service_account=auth_callers["denied"],
        namespace=namespace,
        audience=AUDIENCE,
    )
    wrong_audience = create_sa_token(
        service_account=auth_callers["allowed"],
        namespace=namespace,
        audience=WRONG_AUDIENCE,
    )
    return {
        "allowed": {"Authorization": f"Bearer {allowed}"},
        "denied": {"Authorization": f"Bearer {denied}"},
        "wrong_audience": {"Authorization": f"Bearer {wrong_audience}"},
    }


@pytest.mark.integration
def test_auth_enforcement_matrix(
    deployed_auth_agent: str, auth_headers: dict[str, dict[str, str]]
):
    messages = [{"role": "user", "content": "say hi"}]

    unauthenticated = chat_completion_request(deployed_auth_agent, messages)
    assert unauthenticated.status_code == 401

    authenticated = chat_completion_request(
        deployed_auth_agent, messages, headers=auth_headers["allowed"]
    )
    assert authenticated.status_code == 200

    denied = chat_completion_request(
        deployed_auth_agent, messages, headers=auth_headers["denied"]
    )
    assert denied.status_code == 403

    wrong_audience = chat_completion_request(
        deployed_auth_agent,
        messages,
        headers=auth_headers["wrong_audience"],
    )
    assert wrong_audience.status_code == 401

    health_result = health_check(
        f"{deployed_auth_agent}/health", retries=12, backoff=5.0
    )
    assert health_result["status"] == "healthy"
    assert health_result["agent_initialized"] is True
