"""QG7 deploy/teardown driver for the btest agent set.

Invoke this through `deploy-btest-agents.sh`, not directly. The agent set *is* a
bash array (`AGENTS` in run-btests-pytest.sh), so a bash wrapper sources that
file under `BTEST_LIB_ONLY=1` and hands the tuples over in `QG7_AGENT_CONFIG`.
The indirection is deliberate: deploy and test can then never drift on which
agents exist. When `QG7_AGENT_CONFIG` is unset this module sources the runner
itself, so it stays usable standalone and from unit tests.

Usage:
    deploy-btest-agents.sh                          # deploy the full set
    deploy-btest-agents.sh langgraph/templates/react_agent
    deploy-btest-agents.sh --print-selection        # effective agent ids, one per line
    deploy-btest-agents.sh --undeploy               # tear down what was deployed
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from deploy_agents import (
    DEFAULT_DEPLOY_TIMEOUT,
    DEPLOY_TIMEOUTS,
    ENV_SOURCE_ALIASES,
    EXCLUDED_AGENTS,
    EXTRA_DEPLOYMENTS,
    REPO_ROOT,
    build_env_map,
    container_image_for,
    current_namespace,
    deploy_agent,
    ensure_mlflow_namespace_label,
    get_route,
    is_flow_import,
    load_agent_name,
    missing_aliased_sources,
    oc_token,
    probe_agent,
    readiness_probe,
    refresh_mlflow_token,
    remove_env_file,
    resolve_mlflow_tracking_uri,
    undeploy_agent,
    verify_tracing_enabled,
    write_env_file,
)

logger = logging.getLogger("qg7.deploy")

RUNNER_SCRIPT = Path(__file__).with_name("run-btests-pytest.sh")

# The btest runner's own fan-out is unbounded — it launches every agent at once
# — so there is no bounding pattern to copy. Builds are far heavier than test
# runs, hence a real pool.
DEFAULT_WORKERS = 4

DEPLOYED_RECORD_NAME = "qg7-deployed.txt"


def deployed_record_path() -> Path:
    return Path(os.environ.get("RUNNER_TEMP", "/tmp")) / DEPLOYED_RECORD_NAME


@dataclass(frozen=True)
class AgentTarget:
    agent_id: str
    url_env_var: str
    deployment_name: str
    namespace: str
    agent_dir: Path

    @property
    def deployment_names(self) -> tuple[str, ...]:
        return (self.deployment_name, *EXTRA_DEPLOYMENTS.get(self.agent_id, ()))

    @property
    def deploy_timeout(self) -> int:
        return DEPLOY_TIMEOUTS.get(self.agent_id, DEFAULT_DEPLOY_TIMEOUT)


# ---------------------------------------------------------------------------
# Agent set
# ---------------------------------------------------------------------------


def read_agent_config() -> list[str]:
    """Return the raw `AGENTS` tuples from run-btests-pytest.sh."""
    raw = os.environ.get("QG7_AGENT_CONFIG")
    if raw is None:
        raw = subprocess.run(
            [
                "bash",
                "-c",
                f'BTEST_LIB_ONLY=1 source "{RUNNER_SCRIPT}"; '
                'printf "%s\\n" "${AGENTS[@]}"',
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    return [line for line in (ln.strip() for ln in raw.splitlines()) if line]


def parse_agent_tuples(tuples: list[str], namespace: str) -> list[AgentTarget]:
    """Parse "agent_id|url_env_var|deployment_name[|namespace_override]"."""
    targets = []
    for entry in tuples:
        fields = entry.split("|")
        if len(fields) < 3:
            raise ValueError(f"Malformed agent tuple: {entry!r}")
        agent_id, url_env_var, deployment_name = fields[0], fields[1], fields[2]
        override = fields[3] if len(fields) > 3 and fields[3] else None
        targets.append(
            AgentTarget(
                agent_id=agent_id,
                url_env_var=url_env_var,
                deployment_name=deployment_name,
                namespace=override or namespace,
                agent_dir=REPO_ROOT / "agents" / agent_id,
            )
        )
    return targets


def select_agents(
    targets: list[AgentTarget],
    requested: list[str],
    environ: dict[str, str] | None = None,
) -> list[AgentTarget]:
    """Apply the caller's allowlist, subtract EXCLUDED_AGENTS, then drop agents
    whose aliased env vars are unset.

    The exclusion is applied whether or not the caller named agents explicitly:
    a workflow_dispatch asking for an excluded agent would otherwise deploy one
    this landing does not model.

    The env skip follows QG4's precedent (agent-deployment-test.yaml:102, which
    skips autogen-mcp-agent when MCP_SERVER_URL is empty): one unconfigured agent
    should not fail the gate for the other eight. It happens at selection time,
    so the runner's argv never names an agent the deploy pass dropped.
    """
    by_id = {t.agent_id: t for t in targets}
    if requested:
        unknown = [a for a in requested if a not in by_id]
        if unknown:
            raise SystemExit(
                f"Unknown agent(s): {', '.join(unknown)}\n"
                "Available:\n  " + "\n  ".join(by_id)
            )
        chosen = [by_id[a] for a in requested]
    else:
        chosen = list(targets)

    kept = []
    for target in chosen:
        if target.agent_id in EXCLUDED_AGENTS:
            logger.warning("Excluding %s (see EXCLUDED_AGENTS)", target.agent_id)
            continue
        unset = missing_aliased_sources(target.agent_dir, target.agent_id, environ)
        if unset:
            logger.warning(
                "Skipping %s: %s unset, and its alias exists because the shared "
                "value points elsewhere -- deploying it would test the wrong "
                "endpoint. Set them to include it.",
                target.agent_id,
                ", ".join(unset),
            )
            continue
        kept.append(target)
    return kept


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------


class _DeployedRecord:
    """Append-only record of agents whose `make deploy` returned.

    Written *before* the readiness and tracing gates so an agent that came up
    but failed a gate is still torn down. The teardown pass reads this file, so
    a crash midway through deploy still tears down exactly what came up — and a
    leftover afterwards is a real alarm rather than noise.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def reset(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def add(self, agent_id: str) -> None:
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(f"{agent_id}\n")
                handle.flush()

    def read(self) -> list[str]:
        if not self.path.is_file():
            return []
        return [
            line
            for line in (ln.strip() for ln in self.path.read_text().splitlines())
            if line
        ]


def _deploy_one(
    target: AgentTarget,
    *,
    namespace: str,
    tracking_uri: str,
    token: str,
    record: _DeployedRecord,
) -> None:
    """Steps 1-5 for one agent, in the only order that works."""
    agent_name = load_agent_name(target.agent_dir)
    write_env_file(
        target.agent_dir,
        build_env_map_for(target, namespace, agent_name, tracking_uri, token),
    )

    # 1. build + deploy
    routes = deploy_agent(
        target.agent_dir,
        namespace,
        deployment_names=target.deployment_names,
        deploy_timeout=target.deploy_timeout,
    )

    # 2. record before any gate below
    record.add(target.agent_id)

    # 3. readiness
    probe = readiness_probe(target.agent_dir)
    for deployment_name, route_url in routes.items():
        logger.info("Probing %s at %s%s", deployment_name, route_url, probe.path)
        probe_agent(route_url, probe)

    # 4. tracing
    for deployment_name in target.deployment_names:
        verify_tracing_enabled(
            deployment_name,
            namespace,
            tracking_uri=tracking_uri,
            token=token,
        )

    # 5. token refresh last — the secret must exist and the pod must be up for
    #    the rollout restart to take.
    refresh_mlflow_token(namespace, target.deployment_names, token=token)


def build_env_map_for(
    target: AgentTarget,
    namespace: str,
    agent_name: str,
    tracking_uri: str,
    token: str,
) -> dict[str, str]:
    return build_env_map(
        target.agent_dir,
        namespace,
        container_image=container_image_for(agent_name, namespace),
        include_mlflow=True,
        deployment_name=target.deployment_name,
        tracking_uri=tracking_uri,
        token=token,
        aliases=ENV_SOURCE_ALIASES.get(target.agent_id),
    )


def _probe_flow_import(target: AgentTarget) -> None:
    """Probe-only: never build, deploy, or undeploy a flow-import agent.

    Langflow runs on a pre-deployed platform instance and traces via Langfuse,
    not MLflow, so the tracing gate does not apply either.
    """
    override = os.environ.get("LANGFLOW_AGENT_URL", "").strip()
    if override:
        if not override.startswith("https://"):
            raise SystemExit(f"LANGFLOW_AGENT_URL must use https://: {override}")
        route_url = override.rstrip("/").removesuffix("/health_check")
    else:
        route_url = get_route(target.deployment_name, namespace=target.namespace)
    probe = readiness_probe(target.agent_dir)
    logger.info(
        "Probing pre-deployed %s at %s%s", target.agent_id, route_url, probe.path
    )
    probe_agent(route_url, probe)


def run_deploy(targets: list[AgentTarget], workers: int) -> int:
    namespace = current_namespace()
    logger.info("Namespace: %s", namespace)

    record = _DeployedRecord(deployed_record_path())
    record.reset()

    ensure_mlflow_namespace_label(namespace)
    # Resolved once, before any deploy: the "discover from an existing
    # deployment" link in the chain cannot fire for the first agent of a fresh
    # namespace.
    tracking_uri = resolve_mlflow_tracking_uri(namespace)
    token = oc_token()

    flow_targets = [t for t in targets if is_flow_import(t.agent_dir)]
    build_targets = [t for t in targets if not is_flow_import(t.agent_dir)]

    failures: list[tuple[str, BaseException]] = []
    stop = threading.Event()
    failures_lock = threading.Lock()

    def worker(target: AgentTarget) -> None:
        # Fail fast: stop feeding the pool, but let in-flight workers finish so
        # their agents land in the record and stay tearable-down. A partial
        # deploy hands the runner a set that emits NO_ROUTE and fails the gate
        # anyway, so burning the rest of the pool's build time buys nothing.
        if stop.is_set():
            logger.warning("Skipping %s — an earlier agent failed", target.agent_id)
            return
        try:
            _deploy_one(
                target,
                namespace=namespace,
                tracking_uri=tracking_uri,
                token=token,
                record=record,
            )
            logger.info("Deployed %s", target.agent_id)
        except Exception as exc:
            stop.set()
            try:
                remove_env_file(target.agent_dir)
            except Exception:
                logger.debug("Could not clean up .env for %s", target.agent_id)
            with failures_lock:
                failures.append((target.agent_id, exc))
            logger.error("FAILED %s: %s", target.agent_id, exc)

    for target in flow_targets:
        try:
            _probe_flow_import(target)
            logger.info("Probed pre-deployed %s", target.agent_id)
        except Exception as exc:
            stop.set()
            with failures_lock:
                failures.append((target.agent_id, exc))
            logger.error("FAILED %s: %s", target.agent_id, exc)

    if build_targets:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(worker, build_targets))

    if failures:
        logger.error("%d agent(s) failed:", len(failures))
        for agent_id, exc in failures:
            logger.error("  %s: %s", agent_id, exc)
        return 1
    logger.info(
        "Ready: %d deployed, %d pre-deployed", len(build_targets), len(flow_targets)
    )
    return 0


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


def run_undeploy(targets: list[AgentTarget]) -> int:
    record = _DeployedRecord(deployed_record_path())
    if not record.path.is_file():
        # The deploy pass truncates this file before doing anything, so its
        # absence means the deploy pass never ran and nothing was deployed.
        logger.warning("No %s — nothing to tear down", record.path)
        return 0
    deployed = record.read()

    by_id = {t.agent_id: t for t in targets}
    for agent_id in deployed:
        target = by_id.get(agent_id)
        agent_dir = target.agent_dir if target else REPO_ROOT / "agents" / agent_id
        if is_flow_import(agent_dir):
            logger.info("Skipping undeploy of flow-import agent %s", agent_id)
            continue
        logger.info("Undeploying %s", agent_id)
        undeploy_agent(agent_dir)
        remove_env_file(agent_dir)

    record.path.unlink(missing_ok=True)
    logger.info("Torn down %d agent(s)", len(deployed))
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deploy-btest-agents.sh",
        description="Deploy or tear down the QG7 btest agent set.",
    )
    parser.add_argument(
        "agents",
        nargs="*",
        help="template-layout agent ids; omit for the full set",
    )
    parser.add_argument(
        "--print-selection",
        action="store_true",
        help=(
            "print the effective agent ids (one per line) and exit. The btest "
            "runner is allowlist-only, so its argv must be this same list."
        ),
    )
    parser.add_argument("--undeploy", action="store_true", help="teardown pass")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # --print-selection must not need a cluster; the namespace only labels the
    # targets and is not consulted for the id list.
    namespace = "" if args.print_selection else current_namespace()
    targets = select_agents(
        parse_agent_tuples(read_agent_config(), namespace), args.agents
    )

    if args.print_selection:
        for target in targets:
            print(target.agent_id)
        return 0

    if not targets:
        logger.error("Empty agent selection")
        return 1

    if args.undeploy:
        return run_undeploy(targets)
    return run_deploy(targets, args.workers)


if __name__ == "__main__":
    sys.exit(main())
