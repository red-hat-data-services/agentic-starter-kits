"""Deploy/teardown helpers for the QG7 cluster behavioral test gate.

QG7 (`run-btests-pytest.sh`) assumes agents are already deployed, healthy, and
tracing to MLflow. Nothing in CI satisfied that assumption: QG4 undeploys every
agent in a `finally` block, and QG4-style deploys carry no `MLFLOW_*` config at
all. This module gives QG7 its own deploy/teardown so the gate is
self-contained.

Scope: QG7 only. The build/deploy/undeploy bodies are lifted from the existing
per-agent `deployed_agent` fixtures under `agents/*/*/*/tests/integration/` so
behaviour is identical; those fixtures are deliberately left untouched.
`integration.utils` is imported read-only. A follow-up may promote this module
to a shared one and migrate the duplicated fixtures onto it.

The MLflow steps (namespace label, per-agent experiment name, Helm-safe token
refresh, tracing verification) follow the `deploy-agents` skill, which lives in
a separate repository (`agentic-starter-kits-skills`) and is versioned
independently -- nothing keeps the two in sync. Read at commit 83dedac.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

# `integration.utils` lives under tests/, which is on neither pytest's
# `pythonpath` nor the default sys.path. The agent Makefiles export the same
# entry (see e.g. react_agent/Makefile's test-integration target); doing it here
# keeps `pyproject.toml` unchanged and lets the unit tests import this module
# directly.
_TESTS_DIR = REPO_ROOT / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from integration.utils import (  # noqa: E402
    MakeTargetError,
    RouteNotFoundError,
    _redact,
    get_route,
    health_check,
    load_agent_name,
    run_make,
)

logger = logging.getLogger(__name__)

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"

# Agents in the btest AGENTS array that this landing does not deploy. The array
# itself keeps its entry -- it stays the single source of truth for the agent
# set -- and the skip is applied by filtering here, so both the deploy pass and
# the runner's argv see the same reduced list.
EXCLUDED_AGENTS = (
    # RHAIENG-7081: guardrailed_agent needs `make deploy-guardrails` (NemoGuardrails
    # CR + ConfigMap + Secret) first, and its BASE_URL must be the guardrails
    # service URL rather than the shared one. Passing the shared BASE_URL would
    # bypass the proxy and green the gate against an *unguarded* agent -- silent,
    # so it gets its own ticket rather than a rushed special case.
    "langgraph/examples/guardrailed_agent",
    # RHAIENG-7095: the OGX llama-stack has no vector stores, so VECTOR_STORE_ID is
    # stale and retrieval fails with `Vector_store '...' not found`. Cluster data,
    # not code -- the ENV_SOURCE_ALIASES entry below stays, ready for the store's
    # return.
    "langgraph/templates/agentic_rag",
)

FLOW_IMPORT = "flow-import"
_KNOWN_DEPLOYMENT_MODELS = (None, FLOW_IMPORT)

# One `make deploy` can produce more than one Deployment. The btest AGENTS array
# only names the one it exercises, so extras are listed here for probing and
# token refresh.
EXTRA_DEPLOYMENTS: dict[str, tuple[str, ...]] = {
    "a2a/templates/langgraph_crewai_agent": ("a2a-crew-agent",),
}

# a2a's two-phase Helm deploy waits on two rollouts; 300s is not enough.
DEPLOY_TIMEOUTS: dict[str, int] = {
    "a2a/templates/langgraph_crewai_agent": 600,
}
DEFAULT_DEPLOY_TIMEOUT = 300
DEFAULT_BUILD_TIMEOUT = 600
DEFAULT_UNDEPLOY_TIMEOUT = 120
DEFAULT_ROLLOUT_TIMEOUT = 180

# Agents that need different *values* for the standard vars. QG7's env block is
# job-level rather than per-matrix, so the swap QG4 does with matrix `include`
# happens here instead. Mapping is {agent var: source env var}; the source only
# wins when it is set, mirroring QG4's `${{ matrix.BASE_URL || vars.BASE_URL }}`.
ENV_SOURCE_ALIASES: dict[str, dict[str, str]] = {
    # Talks to OpenAI, not the cluster LLM (agent-deployment-test.yaml:81-83, 106).
    "vanilla_python/templates/openai_responses_agent": {
        "API_KEY": "OPENAI_API_KEY",
        "BASE_URL": "OPENAI_BASE_URL",
        "MODEL_ID": "OPENAI_MODEL_ID",
    },
    # Talks to the llama-stack/OGX endpoint that also serves its vector store,
    # not the plain vLLM service. With the shared BASE_URL its retrieval calls
    # 404 on /v1/vector-io/query and every retrieval btest fails at request time
    # -- the deploy gates pass, because /health does not touch the vector store.
    "langgraph/templates/agentic_rag": {
        "BASE_URL": "OGX_BASE_URL",
        "MODEL_ID": "OGX_MODEL_ID",
    },
}

MLFLOW_OPERATOR_CRD = "mlflowoperators.components.platform.opendatahub.io"
MLFLOW_ROUTE_NAMESPACE = "redhat-ods-applications"
MLFLOW_TOKEN_SECRET_KEY = "mlflow-tracking-token"

# Never forwarded from the ambient environment -- CONTAINER_IMAGE* is computed
# here, and a stray PORT on the runner would silently break the container.
_ENV_PASSTHROUGH_DENYLIST = frozenset(
    {"PORT", "CONTAINER_IMAGE", "CONTAINER_IMAGE_CREW", "CONTAINER_IMAGE_LANGGRAPH"}
)

_ENV_BACKUP_SUFFIX = ".qg7.bak"


class DeploymentModelError(Exception):
    """agent.yaml declares a deploymentModel this module does not know how to handle."""


class MissingEnvError(Exception):
    def __init__(self, agent_dir: Path, missing: list[str]):
        self.agent_dir = agent_dir
        self.missing = missing
        super().__init__(
            f"{agent_dir}: missing required env vars: {', '.join(missing)}. "
            "Set them in the CI workflow env block or export them locally."
        )


class MLflowConfigError(Exception):
    """MLflow tracking configuration could not be resolved."""


class TracingNotEnabledError(Exception):
    """An agent came up but is not tracing to MLflow."""


class HardcodedTokenError(Exception):
    """MLFLOW_TRACKING_TOKEN is a literal value instead of a secretKeyRef."""


# ---------------------------------------------------------------------------
# oc helpers
# ---------------------------------------------------------------------------


def _oc(
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["oc", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        input=stdin,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"oc {' '.join(args)} failed ({result.returncode})\n"
            f"stdout: {_redact(result.stdout)}\n"
            f"stderr: {_redact(result.stderr)}"
        )
    return result


def current_namespace() -> str:
    """Resolve the namespace the same way run-btests-pytest.sh does."""
    return _oc(["project", "-q"]).stdout.strip()


def oc_token() -> str:
    """Current bearer token.

    On a CI runner this is exactly `secrets.OC_TOKEN`: setup-cluster consumes it
    once via `oc login --token=...` and it lives in the kubeconfig thereafter.
    """
    token = _oc(["whoami", "-t"]).stdout.strip()
    if not token:
        raise MLflowConfigError("`oc whoami -t` returned an empty token")
    return token


# ---------------------------------------------------------------------------
# agent.yaml
# ---------------------------------------------------------------------------


def load_agent_spec(agent_dir: str | Path) -> dict:
    data = yaml.safe_load((Path(agent_dir) / "agent.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{agent_dir}/agent.yaml did not parse to a mapping")
    return data


def deployment_model(agent_dir: str | Path) -> str | None:
    """Return the declared deploymentModel, rejecting ones we cannot handle.

    Failing loudly matters: an unrecognized model silently falling through to
    the standard build path would try to `make build-openshift` an agent that
    has no Dockerfile.
    """
    model = load_agent_spec(agent_dir).get("deploymentModel")
    if model is not None:
        model = str(model).strip() or None
    if model not in _KNOWN_DEPLOYMENT_MODELS:
        raise DeploymentModelError(
            f"{agent_dir}/agent.yaml: unrecognized deploymentModel {model!r}. "
            f"Known values: {', '.join(str(m) for m in _KNOWN_DEPLOYMENT_MODELS)}."
        )
    return model


def is_flow_import(agent_dir: str | Path) -> bool:
    return deployment_model(agent_dir) == FLOW_IMPORT


def load_agent_env_spec(agent_dir: str | Path) -> tuple[list[str], list[str]]:
    """Return (required, optional) env var names from agent.yaml.

    `agent.yaml` `env.required`/`env.optional` is the declarative source of
    truth -- the Makefile `_check-env` target reads the same block. Note the
    per-agent integration conftests have drifted from it (a2a and
    react_with_database_memory both omit `API_KEY`); driving off agent.yaml
    makes those two stricter, which is the intended direction.
    """
    deployment_model(agent_dir)  # validate before anything reads the env block
    env = load_agent_spec(agent_dir).get("env") or {}
    required = [str(v) for v in (env.get("required") or [])]
    optional = [str(v) for v in (env.get("optional") or [])]
    return required, optional


# ---------------------------------------------------------------------------
# MLflow configuration
# ---------------------------------------------------------------------------


def _is_forbidden(result: subprocess.CompletedProcess[str]) -> bool:
    return "forbidden" in (result.stderr or "").lower()


def mlflow_operator_present() -> bool | None:
    """True on RHOAI 3.5+, where MLflow is managed by the MLflow operator.

    None when the check itself is not permitted. CRDs are cluster-scoped, and a
    namespace-scoped CI ServiceAccount cannot read them -- collapsing that into
    False would claim "RHOAI < 3.5" on a 3.5 cluster and silently skip the
    namespace label.
    """
    result = _oc(["get", "crd", MLFLOW_OPERATOR_CRD], check=False)
    if result.returncode == 0:
        return True
    return None if _is_forbidden(result) else False


def _mlflow_label_present(namespace: str) -> bool:
    """True if the namespace already carries `mlflow-tracking=enabled`.

    Reading its own namespace is within a namespace-admin's rights even when
    reading CRDs cluster-wide is not, so this works where the CRD probe does not.
    """
    result = _oc(
        [
            "get",
            "namespace",
            namespace,
            "-o",
            "jsonpath={.metadata.labels.mlflow-tracking}",
        ],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "enabled"


def ensure_mlflow_namespace_label(namespace: str) -> bool:
    """Label the namespace for MLflow tracking (skill Step 0a).

    RHOAI 3.5+ maps MLflow workspaces 1:1 onto labelled namespaces. Without the
    label agents fail with `RESOURCE_DOES_NOT_EXIST: Workspace '<ns>' not
    found`. Pre-3.5 clusters have no such concept, so the label is skipped.
    Returns True if the label is in place.
    """
    present = mlflow_operator_present()
    if present is False:
        logger.info(
            "MLflow operator CRD absent (RHOAI < 3.5) — skipping namespace label"
        )
        return False

    if present is None:
        # Operator presence unknown. If the label is already there the point is
        # moot; otherwise say so loudly rather than deploying agents that will
        # fail at runtime with `Workspace not found`.
        if _mlflow_label_present(namespace):
            logger.info(
                "Cannot read CRDs (not permitted); namespace %s is already "
                "labelled mlflow-tracking=enabled",
                namespace,
            )
            return True
        logger.warning(
            "Cannot read CRDs (not permitted), so RHOAI version is unknown and "
            "namespace %s is not labelled mlflow-tracking=enabled. Attempting "
            "to label it anyway.",
            namespace,
        )

    result = _oc(
        ["label", "namespace", namespace, "mlflow-tracking=enabled", "--overwrite"],
        check=False,
    )
    if result.returncode != 0:
        if present is None and _is_forbidden(result):
            raise MLflowConfigError(
                f"Namespace {namespace} is not labelled mlflow-tracking=enabled "
                "and this credential may label neither it nor read the MLflow "
                "operator CRD. On RHOAI 3.5+ every agent would come up untraced "
                f"with `Workspace '{namespace}' not found`. Pre-label the "
                "namespace out of band: "
                f"oc label namespace {namespace} mlflow-tracking=enabled"
            )
        raise RuntimeError(
            f"oc label namespace {namespace} failed ({result.returncode})\n"
            f"stdout: {_redact(result.stdout)}\n"
            f"stderr: {_redact(result.stderr)}"
        )
    logger.info("Labelled namespace %s with mlflow-tracking=enabled", namespace)
    return True


def _tracking_uri_from_deployments(namespace: str) -> str | None:
    result = _oc(
        ["get", "deployments", "-n", namespace, "-o", "json"], check=False, timeout=60
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        items = json.loads(result.stdout).get("items", [])
    except json.JSONDecodeError:
        return None
    for item in items:
        containers = (
            item.get("spec", {}).get("template", {}).get("spec", {}).get("containers")
            or []
        )
        for container in containers:
            for env in container.get("env") or []:
                if env.get("name") == "MLFLOW_TRACKING_URI" and env.get("value"):
                    return str(env["value"])
    return None


def _tracking_uri_candidates() -> list[str]:
    """Every plausible tracking URI a route in the cluster suggests, best first.

    RHOAI 3.5 fronts the tracking server with the data-science gateway at
    `/mlflow`; the standalone `mlflow` route in `redhat-ods-applications` is
    still present on such clusters but answers 404. Older layouts only have the
    standalone route. Both shapes are offered and the caller picks the one that
    actually responds.
    """
    result = _oc(["get", "route", "-A", "-o", "json"], check=False, timeout=60)
    if result.returncode != 0 or not result.stdout.strip():
        if _is_forbidden(result):
            # Listing routes is cluster-scoped; a namespace-scoped CI
            # ServiceAccount cannot do it, so this link of the chain is simply
            # unavailable there. Set MLFLOW_TRACKING_URI explicitly instead.
            logger.warning(
                "Cannot list routes cluster-wide (not permitted) — route "
                "discovery unavailable"
            )
        return []
    try:
        items = json.loads(result.stdout).get("items", [])
    except json.JSONDecodeError:
        return []

    gateways: list[str] = []
    standalone: list[str] = []
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        host = item.get("spec", {}).get("host")
        if not host:
            continue
        if "data-science-gateway" in name:
            gateways.append(f"https://{host}/mlflow")
        elif "mlflow" in name and meta.get("namespace") == MLFLOW_ROUTE_NAMESPACE:
            standalone.append(f"https://{host}")
    return gateways + standalone


def _tracking_uri_from_route(token: str | None = None) -> str | None:
    """First route-derived URI whose MLflow API answers, or None.

    Unvalidated route discovery is worse than none: a URI that 404s reaches
    every agent's `.env`, so all of them come up untraced and the tracing gate
    reports a broken token rather than a bad URI.
    """
    candidates = _tracking_uri_candidates()
    if not candidates:
        return None
    try:
        token = token or oc_token()
    except MLflowConfigError:
        return candidates[0]
    for candidate in candidates:
        if _mlflow_server_reachable(candidate, token):
            return candidate
    logger.warning(
        "No route-derived MLflow URI answered /api/3.0/mlflow/server-info (tried: %s)",
        ", ".join(candidates),
    )
    return None


def resolve_mlflow_tracking_uri(namespace: str) -> str:
    """Resolve MLFLOW_TRACKING_URI once, for the whole deploy pass.

    Chain: explicit env override, then an existing deployment in the namespace,
    then the MLflow route in `redhat-ods-applications`. The middle link needs a
    prior deployment, which will not exist on the first agent of a fresh
    namespace -- which is exactly why the caller resolves this once up front
    rather than per agent.
    """
    override = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if override:
        logger.info("MLFLOW_TRACKING_URI taken from the environment")
        return override

    discovered = _tracking_uri_from_deployments(namespace)
    if discovered:
        logger.info("MLFLOW_TRACKING_URI discovered from an existing deployment")
        return discovered

    routed = _tracking_uri_from_route()
    if routed:
        logger.info("MLFLOW_TRACKING_URI discovered from a route: %s", routed)
        return routed

    raise MLflowConfigError(
        "Could not resolve MLFLOW_TRACKING_URI: no env override, no existing "
        f"deployment in {namespace} carrying it, and no MLflow or data-science "
        "gateway route was visible in the cluster. Without it the btest runner "
        "cannot enrich results with trace data. Note that route discovery needs "
        "cluster-wide route read, which a namespace-scoped CI ServiceAccount "
        "does not have — in CI, set the MLFLOW_TRACKING_URI repository variable."
    )


def mlflow_env(
    namespace: str,
    deployment_name: str,
    *,
    tracking_uri: str | None = None,
    token: str | None = None,
) -> dict[str, str]:
    """MLflow env block for one agent's .env (skill Step 3d)."""
    return {
        "MLFLOW_TRACKING_URI": tracking_uri or resolve_mlflow_tracking_uri(namespace),
        # Unique per agent. A shared experiment name cross-contaminates traces
        # (RHAIENG-6743). The runner reads this per-agent value off the
        # deployment spec and only falls back to a global one.
        "MLFLOW_EXPERIMENT_NAME": f"{namespace}/{deployment_name}",
        # Mandatory on OpenShift MLflow; without it the API returns
        # "Workspace context is required".
        "MLFLOW_WORKSPACE": namespace,
        "MLFLOW_TRACKING_INSECURE_TLS": "true",
        "MLFLOW_TRACKING_TOKEN": token or oc_token(),
    }


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------


def missing_aliased_sources(
    agent_dir: Path, agent_id: str, environ: dict[str, str] | None = None
) -> list[str]:
    """Aliased env vars this agent needs that are unset, if any.

    An agent with an ENV_SOURCE_ALIASES entry cannot be tested at all without it:
    the alias exists because the shared value points somewhere else. Rather than
    fail the whole gate for one unconfigured agent, the selection drops it --
    matching QG4, which skips autogen-mcp-agent the same way when MCP_SERVER_URL
    is empty (agent-deployment-test.yaml:102).

    Only *required* vars count. An unset alias for an optional var just means the
    var is omitted, which is fine.
    """
    environ = os.environ if environ is None else environ
    aliases = ENV_SOURCE_ALIASES.get(agent_id, {})
    if not aliases:
        return []
    required, _ = load_agent_env_spec(agent_dir)
    return sorted(
        alias
        for var, alias in aliases.items()
        if var in required and not environ.get(alias, "").strip()
    )


def build_env_map(
    agent_dir: str | Path,
    namespace: str,
    *,
    container_image: str,
    include_mlflow: bool,
    deployment_name: str | None = None,
    tracking_uri: str | None = None,
    token: str | None = None,
    environ: dict[str, str] | None = None,
    aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the .env contents for one agent from its agent.yaml env block."""
    environ = os.environ if environ is None else environ
    aliases = aliases or {}
    required, optional = load_agent_env_spec(agent_dir)

    def read(var: str) -> tuple[str, str]:
        """Resolve one var, returning (value, the env name it should have come from).

        An ENV_SOURCE_ALIASES entry exists precisely because the shared value is
        *wrong* for this agent, so an empty alias must not fall back to it: GitHub
        substitutes "" for an undefined variable, and the fallback would quietly
        deploy the agent against the shared endpoint and pass. Report the alias as
        missing instead, so the gate fails loudly and names what to set
        (RHAIENG-7097).
        """
        alias = aliases.get(var)
        if alias:
            return environ.get(alias, "").strip(), alias
        return environ.get(var, "").strip(), var

    env_map: dict[str, str] = {}
    missing: list[str] = []
    for var in required:
        if var in _ENV_PASSTHROUGH_DENYLIST:
            continue
        value, source = read(var)
        if value:
            env_map[var] = value
        else:
            missing.append(source)
    if missing:
        # Report every missing name at once — one CI round trip per fix, not one
        # per variable.
        raise MissingEnvError(Path(agent_dir), missing)

    for var in optional:
        if var in _ENV_PASSTHROUGH_DENYLIST:
            continue
        value, _ = read(var)
        if value:
            env_map[var] = value

    env_map["CONTAINER_IMAGE"] = container_image

    if include_mlflow:
        if not deployment_name:
            raise ValueError("deployment_name is required when include_mlflow is set")
        env_map.update(
            mlflow_env(
                namespace,
                deployment_name,
                tracking_uri=tracking_uri,
                token=token,
            )
        )

    return env_map


def container_image_for(agent_name: str, namespace: str) -> str:
    return f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"


def write_env_file(agent_dir: str | Path, env_map: dict[str, str]) -> Path:
    """Write the agent's .env, stashing any pre-existing one.

    Values are never logged -- several of them are credentials. A pre-existing
    .env is moved aside rather than clobbered so a local run does not destroy a
    developer's config; `remove_env_file` puts it back.
    """
    env_path = Path(agent_dir) / ".env"
    backup = env_path.with_name(env_path.name + _ENV_BACKUP_SUFFIX)
    if env_path.exists() and not backup.exists():
        env_path.replace(backup)
    env_path.touch(mode=0o600)
    env_path.chmod(0o600)
    env_path.write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in env_map.items()),
        encoding="utf-8",
    )
    logger.info(
        "Wrote %s (%d vars: %s)",
        env_path,
        len(env_map),
        ", ".join(sorted(env_map)),
    )
    return env_path


def remove_env_file(agent_dir: str | Path) -> None:
    """Remove the .env we wrote, restoring any stashed original."""
    env_path = Path(agent_dir) / ".env"
    backup = env_path.with_name(env_path.name + _ENV_BACKUP_SUFFIX)
    env_path.unlink(missing_ok=True)
    if backup.exists():
        backup.replace(env_path)


# ---------------------------------------------------------------------------
# Readiness probes
# ---------------------------------------------------------------------------


def _check_standard(payload: dict) -> None:
    if payload.get("status") != "healthy":
        raise AssertionError(
            f"/health status is {payload.get('status')!r}, not 'healthy'"
        )
    if payload.get("agent_initialized") is not True:
        raise AssertionError("/health reports agent_initialized is not True")


_AGENT_CARD_FIELDS = (
    "name",
    "supportedInterfaces",
    "version",
    "capabilities",
    "skills",
)


def _check_agent_card(payload: dict) -> None:
    missing = [field for field in _AGENT_CARD_FIELDS if field not in payload]
    if missing:
        raise AssertionError(f"Agent card missing fields: {', '.join(missing)}")


def _check_langflow(payload: dict) -> None:
    for key in ("status", "chat", "db"):
        if payload.get(key) != "ok":
            raise AssertionError(
                f"/health_check {key} is {payload.get(key)!r}, not 'ok'"
            )


@dataclass(frozen=True)
class ReadinessProbe:
    path: str
    check: Callable[[dict], None]


def readiness_probe(agent_dir: str | Path) -> ReadinessProbe:
    """Pick the readiness endpoint for an agent.

    Three shapes are in play, so this cannot be hardcoded to /health: standard
    FastAPI agents, a2a (Starlette, agent card only), and langflow.
    """
    spec = load_agent_spec(agent_dir)
    if deployment_model(agent_dir) == FLOW_IMPORT:
        return ReadinessProbe("/health_check", _check_langflow)
    if str(spec.get("framework", "")).strip().lower() == "a2a":
        return ReadinessProbe("/.well-known/agent-card.json", _check_agent_card)
    return ReadinessProbe("/health", _check_standard)


def probe_agent(
    route_url: str,
    probe: ReadinessProbe,
    *,
    retries: int = 12,
    backoff: float = 5.0,
) -> dict:
    payload = health_check(f"{route_url}{probe.path}", retries=retries, backoff=backoff)
    probe.check(payload)
    return payload


# ---------------------------------------------------------------------------
# Deploy / undeploy
# ---------------------------------------------------------------------------


def wait_for_rollout(
    deployment_name: str,
    namespace: str,
    *,
    timeout: int = DEFAULT_ROLLOUT_TIMEOUT,
) -> None:
    """Block until the deployment's newest ReplicaSet is fully rolled out."""
    _oc(
        [
            "rollout",
            "status",
            f"deployment/{deployment_name}",
            "-n",
            namespace,
            f"--timeout={timeout}s",
        ],
        timeout=timeout + 30,
    )


def deploy_agent(
    agent_dir: str | Path,
    namespace: str,
    *,
    deployment_names: list[str] | tuple[str, ...],
    deploy_timeout: int = DEFAULT_DEPLOY_TIMEOUT,
    build_timeout: int = DEFAULT_BUILD_TIMEOUT,
    rollout_timeout: int = DEFAULT_ROLLOUT_TIMEOUT,
) -> dict[str, str]:
    """Build in-cluster and Helm-deploy, returning {deployment_name: route_url}.

    A mapping rather than a single route because one `make deploy` can produce
    several Deployments (a2a's two-phase Helm produces two). Raises
    RouteNotFoundError if any expected deployment has no route -- fail fast,
    matching the existing fixtures.
    """
    logger.info("Building image on cluster via build-openshift: %s", agent_dir)
    run_make("build-openshift", cwd=agent_dir, timeout=build_timeout)

    logger.info("Deploying to cluster: %s", agent_dir)
    run_make("deploy", cwd=agent_dir, timeout=deploy_timeout)

    # `make deploy` does not wait for the new pods. Without this the readiness
    # probe hits the route, which the *previous* generation's Ready pod still
    # serves, so a crash-looping new image passes the probe and the tracing gate
    # both -- observed live on autogen-mcp-agent, whose new image failed to
    # import while a 27h-old pod answered /health with 200.
    for name in deployment_names:
        wait_for_rollout(name, namespace, timeout=rollout_timeout)

    routes: dict[str, str] = {}
    for name in deployment_names:
        routes[name] = get_route(name, namespace=namespace)
        logger.info("Deployment %s at %s", name, routes[name])
    return routes


def undeploy_agent(agent_dir: str | Path) -> bool:
    """`make undeploy`, tolerating failure with a warning.

    Matches the existing fixtures and the a2a Makefile, which already swallows
    `release: not found`. Returns True when the target succeeded.
    """
    try:
        run_make("undeploy", cwd=agent_dir, timeout=DEFAULT_UNDEPLOY_TIMEOUT)
        return True
    except MakeTargetError:
        logger.warning(
            "Undeploy failed for %s — manual cleanup may be needed",
            agent_dir,
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# MLflow token refresh (skill Step 4)
# ---------------------------------------------------------------------------


def mlflow_token_secret_name(deployment_name: str, namespace: str) -> str | None:
    """Name of the secret backing MLFLOW_TRACKING_TOKEN, or None if unwired.

    Also implements skill Step 4e: a literal `value` instead of a
    `valueFrom.secretKeyRef` means secret refreshes silently do nothing, so it
    is an error rather than a warning.
    """
    result = _oc(
        ["get", "deployment", deployment_name, "-n", namespace, "-o", "json"],
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        return None
    containers = (
        json.loads(result.stdout)
        .get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers")
        or []
    )
    for container in containers:
        for env in container.get("env") or []:
            if env.get("name") != "MLFLOW_TRACKING_TOKEN":
                continue
            if env.get("value"):
                raise HardcodedTokenError(
                    f"{namespace}/{deployment_name}: MLFLOW_TRACKING_TOKEN is a "
                    "literal value, not a secretKeyRef — token refreshes will "
                    "have no effect. Redeploy via `make deploy` to restore the "
                    "Helm-managed secretKeyRef."
                )
            ref = (env.get("valueFrom") or {}).get("secretKeyRef") or {}
            if ref.get("name"):
                return str(ref["name"])
    return None


def _apply_token_to_secret(secret_name: str, namespace: str, token_b64: str) -> None:
    secret = json.loads(
        _oc(
            ["get", "secret", secret_name, "-n", namespace, "-o", "json"], timeout=60
        ).stdout
    )
    secret.setdefault("data", {})[MLFLOW_TOKEN_SECRET_KEY] = token_b64
    # Server-side apply impersonating Helm's field manager. `oc patch` would
    # steal ownership of .data.mlflow-tracking-token and the next `helm upgrade`
    # would fail with `conflict with "kubectl-patch"` (skill Step 4c).
    _oc(
        [
            "apply",
            "--server-side",
            "--force-conflicts",
            "--field-manager=helm",
            "-n",
            namespace,
            "-f",
            "-",
        ],
        stdin=json.dumps(secret),
        timeout=60,
    )


def refresh_mlflow_token(
    namespace: str,
    deployment_names: list[str] | tuple[str, ...],
    *,
    token: str | None = None,
    rollout_timeout: int = 180,
) -> list[str]:
    """Rewrite each deployment's MLflow token secret and restart it.

    Called after the readiness probe, not straight after `make deploy`: the
    secret has to exist and the pod has to be up for the rollout restart to mean
    anything. Returns the secret names that were refreshed.
    """
    token_b64 = base64.b64encode((token or oc_token()).encode("utf-8")).decode("ascii")

    refreshed: list[str] = []
    for deployment_name in deployment_names:
        secret_name = mlflow_token_secret_name(deployment_name, namespace)
        if not secret_name:
            logger.warning(
                "%s/%s has no MLFLOW_TRACKING_TOKEN secretKeyRef — skipping refresh",
                namespace,
                deployment_name,
            )
            continue
        if secret_name not in refreshed:
            _apply_token_to_secret(secret_name, namespace, token_b64)
            refreshed.append(secret_name)
        _oc(
            ["rollout", "restart", f"deployment/{deployment_name}", "-n", namespace],
            timeout=60,
        )
        _oc(
            [
                "rollout",
                "status",
                f"deployment/{deployment_name}",
                "-n",
                namespace,
                f"--timeout={rollout_timeout}s",
            ],
            timeout=rollout_timeout + 30,
        )
    return refreshed


# ---------------------------------------------------------------------------
# Tracing verification (skill Step 4f)
# ---------------------------------------------------------------------------

# a2a tags its markers with the framework -- `[Tracing Enabled LangGraph]`,
# `[Tracing CrewAI] Failed to configure` -- so an exact-string match never fires
# for either of its deployments and both silently fall through to the weaker
# token-only fallback. Match the bracketed tag instead of a literal.
_TRACING_OK = re.compile(r"\[Tracing Enabled[^\]]*\]")
_TRACING_FAILED = re.compile(r"\[Tracing[^\]]*\] Failed to configure")

# How long to wait for one of those markers after the rollout reports Ready.
# Observed on a live cluster: ~20s between `oc rollout status` returning and the
# agent printing [Tracing Enabled].
_TRACING_STARTUP_WAIT = 90.0
_TRACING_POLL_INTERVAL = 5.0

_TRACING_HINTS = (
    (
        "matches the configured selector",
        "the namespace is missing the mlflow-tracking=enabled label "
        "(RHOAI 3.5+; see ensure_mlflow_namespace_label)",
    ),
    (
        "RESOURCE_DOES_NOT_EXIST",
        "the namespace is missing the mlflow-tracking=enabled label "
        "(RHOAI 3.5+; see ensure_mlflow_namespace_label)",
    ),
    (
        "UNAUTHENTICATED",
        "the MLflow operator is not deployed or the tracking server is not "
        "running (check the DataScienceCluster mlflowoperator managementState)",
    ),
    (
        "Expecting value: line 1 column 1",
        "MLflow returned non-JSON (usually a 302 OAuth redirect) — the tracking "
        "token is expired or invalid",
    ),
)


def _tracing_hint(logs: str) -> str:
    for needle, hint in _TRACING_HINTS:
        if needle in logs:
            return hint
    return "no recognized failure pattern; see the pod logs above"


def _mlflow_server_reachable(tracking_uri: str, token: str) -> bool:
    """True when the token gets JSON out of the MLflow API, not an HTML redirect."""
    try:
        with httpx.Client(verify=False, timeout=15.0, follow_redirects=False) as client:
            resp = client.get(
                f"{tracking_uri.rstrip('/')}/api/3.0/mlflow/server-info",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return False
    try:
        resp.json()
    except ValueError:
        return False
    return True


def verify_tracing_enabled(
    deployment_name: str,
    namespace: str,
    *,
    tracking_uri: str | None = None,
    token: str | None = None,
    tail: int = 200,
    startup_wait: float = _TRACING_STARTUP_WAIT,
    poll_interval: float = _TRACING_POLL_INTERVAL,
) -> None:
    """Raise unless the agent's startup logs show MLflow tracing came up.

    `/health` returns 200 OK while tracing is broken; the symptom only shows up
    much later as btests skipping with "tool_calls not exposed". Gating here
    stops QG7 burning its whole timeout producing unusable results.

    The marker is polled rather than read once: a rollout counts a pod Ready
    before the app finishes its startup logging, so a single read lands either
    on the outgoing pod (whose marker has scrolled past `tail`) or on a new pod
    that has not printed it yet. Both look identical to a genuinely broken
    agent, and both would fall through to the token check below -- which proves
    the *token* works, not that the *agent* is tracing.
    """
    deadline = time.monotonic() + startup_wait
    logs = ""
    while True:
        logs = _oc(
            [
                "logs",
                f"deployment/{deployment_name}",
                "-n",
                namespace,
                f"--tail={tail}",
            ],
            check=False,
            timeout=60,
        ).stdout

        if _TRACING_OK.search(logs):
            logger.info("Tracing enabled for %s/%s", namespace, deployment_name)
            return

        if _TRACING_FAILED.search(logs):
            raise TracingNotEnabledError(
                f"{namespace}/{deployment_name}: MLflow tracing failed to configure — "
                f"{_tracing_hint(logs)}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    # Ambiguous: neither marker appeared within the startup window. Ask MLflow
    # directly rather than guessing from log truncation.
    if tracking_uri and _mlflow_server_reachable(tracking_uri, token or oc_token()):
        logger.warning(
            "%s/%s: no [Tracing Enabled] marker in the last %d log lines, but the "
            "MLflow token is valid — treating as enabled",
            namespace,
            deployment_name,
            tail,
        )
        return

    raise TracingNotEnabledError(
        f"{namespace}/{deployment_name}: no [Tracing Enabled] marker in the last "
        f"{tail} log lines and the MLflow token did not return JSON from "
        "/api/3.0/mlflow/server-info (HTML or a 302 means it is expired)"
    )


__all__ = [
    "DEFAULT_BUILD_TIMEOUT",
    "DEFAULT_DEPLOY_TIMEOUT",
    "DEPLOY_TIMEOUTS",
    "EXCLUDED_AGENTS",
    "ENV_SOURCE_ALIASES",
    "missing_aliased_sources",
    "EXTRA_DEPLOYMENTS",
    "FLOW_IMPORT",
    "INTERNAL_REGISTRY",
    "REPO_ROOT",
    "DeploymentModelError",
    "HardcodedTokenError",
    "MLflowConfigError",
    "MakeTargetError",
    "MissingEnvError",
    "ReadinessProbe",
    "RouteNotFoundError",
    "TracingNotEnabledError",
    "build_env_map",
    "container_image_for",
    "current_namespace",
    "deploy_agent",
    "deployment_model",
    "ensure_mlflow_namespace_label",
    "is_flow_import",
    "load_agent_env_spec",
    "load_agent_name",
    "load_agent_spec",
    "mlflow_env",
    "mlflow_token_secret_name",
    "oc_token",
    "probe_agent",
    "readiness_probe",
    "refresh_mlflow_token",
    "remove_env_file",
    "resolve_mlflow_tracking_uri",
    "undeploy_agent",
    "wait_for_rollout",
    "verify_tracing_enabled",
    "write_env_file",
]
