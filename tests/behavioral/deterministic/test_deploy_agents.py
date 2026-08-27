from __future__ import annotations

import json
import subprocess
from pathlib import Path

import deploy_agents
import deploy_btest_agents
import pytest
from deploy_agents import (
    EXCLUDED_AGENTS,
    DeploymentModelError,
    HardcodedTokenError,
    MissingEnvError,
    build_env_map,
    deployment_model,
    mlflow_env,
    readiness_probe,
)
from deploy_btest_agents import (
    AgentTarget,
    parse_agent_tuples,
    read_agent_config,
    select_agents,
)

REPO_ROOT = deploy_agents.REPO_ROOT
AGENTS_DIR = REPO_ROOT / "agents"

RUNNER_SCRIPT = Path(__file__).with_name("run-btests-pytest.sh")
DRIVER_SCRIPT = Path(__file__).with_name("deploy-btest-agents.sh")

REACT_AGENT = AGENTS_DIR / "langgraph/templates/react_agent"
A2A_AGENT = AGENTS_DIR / "a2a/templates/langgraph_crewai_agent"
LANGFLOW_AGENT = AGENTS_DIR / "langflow/templates/simple_tool_calling_agent"


def _targets() -> list[AgentTarget]:
    return parse_agent_tuples(read_agent_config(), "ci-testing")


# ---------------------------------------------------------------------------
# Agent selection — the runner is allowlist-only, so these two lists must match
# ---------------------------------------------------------------------------


def test_agent_config_matches_runner_array() -> None:
    ids = [t.agent_id for t in _targets()]
    assert len(ids) == 12
    assert "langgraph/templates/react_agent" in ids
    assert len(set(ids)) == len(ids)


_FULLY_CONFIGURED = {
    "OPENAI_API_KEY": "k",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL_ID": "gpt-4o",
    "OGX_BASE_URL": "http://ogx:8321/v1",
    "OGX_MODEL_ID": "vllm/qwen",
}


def test_selection_excludes_the_untestable_agents() -> None:
    selected = select_agents(_targets(), [], environ=_FULLY_CONFIGURED)
    ids = [t.agent_id for t in selected]

    # Derived, not a literal -- the count moves every time an agent is excluded or
    # re-enabled. Sound because test_excluded_agents_are_all_in_the_runner_array
    # proves every excluded id is in the array being subtracted from.
    assert len(ids) == len(_targets()) - len(EXCLUDED_AGENTS)
    for excluded in EXCLUDED_AGENTS:
        assert excluded not in ids


def test_agent_with_unset_aliases_is_skipped_not_failed() -> None:
    """Mirrors QG4's `if: … || vars.MCP_SERVER_URL != ''` (agent-deployment-test.yaml:102).

    One unconfigured agent must not fail the gate for the rest -- but it must not
    deploy against the shared endpoint either, which is what the alias exists to
    prevent.
    """
    selected = select_agents(_targets(), [], environ={})
    ids = [t.agent_id for t in selected]

    assert "vanilla_python/templates/openai_responses_agent" not in ids
    assert "langgraph/templates/react_agent" in ids
    assert len(ids) == len(_targets()) - len(EXCLUDED_AGENTS) - 1


def test_partially_set_aliases_still_skip() -> None:
    """Two of three set is not enough -- the third would fall back silently."""
    selected = select_agents(
        _targets(),
        ["vanilla_python/templates/openai_responses_agent"],
        environ={"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "https://api.openai.com/v1"},
    )

    assert selected == []


def test_exclusion_applies_to_explicit_requests() -> None:
    """A workflow_dispatch naming an excluded agent must not deploy it."""
    selected = select_agents(
        _targets(),
        ["langgraph/templates/react_agent", "langgraph/examples/guardrailed_agent"],
    )

    assert [t.agent_id for t in selected] == ["langgraph/templates/react_agent"]


def test_unknown_agent_is_rejected() -> None:
    with pytest.raises(SystemExit):
        select_agents(_targets(), ["langgraph/templates/does_not_exist"])


def test_print_selection_matches_deploy_selection() -> None:
    """The list handed to the runner is the same one the deploy pass used.

    An agent that was never deployed produces NO_ROUTE, which fails the gate —
    so excluding one from deploy without also removing it from the runner's
    argv would fail QG7 on the very agent we chose to skip.
    """
    printed = subprocess.run(
        ["bash", str(DRIVER_SCRIPT), "--print-selection"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert printed.returncode == 0, printed.stderr

    from_driver = [ln for ln in printed.stdout.splitlines() if ln.strip()]
    from_module = [t.agent_id for t in select_agents(_targets(), [])]
    assert from_driver == from_module


def test_all_selected_agents_resolve_to_a_directory() -> None:
    for target in select_agents(_targets(), []):
        assert (target.agent_dir / "agent.yaml").is_file(), target.agent_id


def test_excluded_agents_are_all_in_the_runner_array() -> None:
    """Guards against EXCLUDED_AGENTS rotting after an AGENTS array edit."""
    ids = {t.agent_id for t in _targets()}
    assert set(EXCLUDED_AGENTS) <= ids


# ---------------------------------------------------------------------------
# Multi-deployment agents
# ---------------------------------------------------------------------------


def test_a2a_has_two_deployments() -> None:
    a2a = next(
        t for t in _targets() if t.agent_id == "a2a/templates/langgraph_crewai_agent"
    )

    assert set(a2a.deployment_names) == {"a2a-crew-agent", "a2a-langgraph-agent"}
    # Two-phase Helm waits on two rollouts; 300s is not enough.
    assert a2a.deploy_timeout == 600


def test_langflow_uses_its_own_namespace() -> None:
    langflow = next(
        t
        for t in _targets()
        if t.agent_id == "langflow/templates/simple_tool_calling_agent"
    )

    assert langflow.namespace == "langflow-agent"
    assert langflow.deployment_name == "langflow"


def test_standard_agent_has_one_deployment() -> None:
    react = next(
        t for t in _targets() if t.agent_id == "langgraph/templates/react_agent"
    )

    assert react.deployment_names == ("langgraph-react-agent",)
    assert react.deploy_timeout == 300


# ---------------------------------------------------------------------------
# deploymentModel
# ---------------------------------------------------------------------------


def test_langflow_is_flow_import() -> None:
    assert deployment_model(LANGFLOW_AGENT) == "flow-import"
    assert deploy_agents.is_flow_import(LANGFLOW_AGENT)


def test_standard_agent_has_no_deployment_model() -> None:
    assert deployment_model(REACT_AGENT) is None
    assert not deploy_agents.is_flow_import(REACT_AGENT)


def test_unknown_deployment_model_raises(tmp_path: Path) -> None:
    """Falling through to the standard build path would try to build an agent
    that may have no Dockerfile — so an unknown model is an error."""
    (tmp_path / "agent.yaml").write_text(
        "name: bogus-agent\ndeploymentModel: config-driven\n", encoding="utf-8"
    )

    with pytest.raises(DeploymentModelError, match="config-driven"):
        deployment_model(tmp_path)


# ---------------------------------------------------------------------------
# Readiness probes — three shapes, so /health cannot be hardcoded
# ---------------------------------------------------------------------------


def test_readiness_probe_standard() -> None:
    probe = readiness_probe(REACT_AGENT)

    assert probe.path == "/health"
    probe.check({"status": "healthy", "agent_initialized": True})
    with pytest.raises(AssertionError):
        probe.check({"status": "healthy", "agent_initialized": False})
    with pytest.raises(AssertionError):
        probe.check({"status": "degraded", "agent_initialized": True})


def test_readiness_probe_a2a() -> None:
    probe = readiness_probe(A2A_AGENT)

    assert probe.path == "/.well-known/agent-card.json"
    probe.check(
        {
            "name": "x",
            "supportedInterfaces": [],
            "version": "1",
            "capabilities": {},
            "skills": [],
        }
    )
    with pytest.raises(AssertionError, match="skills"):
        probe.check(
            {
                "name": "x",
                "supportedInterfaces": [],
                "version": "1",
                "capabilities": {},
            }
        )


def test_readiness_probe_langflow() -> None:
    probe = readiness_probe(LANGFLOW_AGENT)

    assert probe.path == "/health_check"
    probe.check({"status": "ok", "chat": "ok", "db": "ok"})
    with pytest.raises(AssertionError, match="db"):
        probe.check({"status": "ok", "chat": "ok", "db": "error"})


# ---------------------------------------------------------------------------
# build_env_map
# ---------------------------------------------------------------------------

_MLFLOW_KWARGS = {
    "tracking_uri": "https://mlflow.example.test",
    "token": "sha256~fake",
}


def test_build_env_map_reports_every_missing_var_at_once() -> None:
    with pytest.raises(MissingEnvError) as exc:
        build_env_map(
            REACT_AGENT,
            "ci-testing",
            container_image="img:latest",
            include_mlflow=False,
            environ={},
        )

    assert set(exc.value.missing) == {"API_KEY", "BASE_URL", "MODEL_ID"}


def test_build_env_map_demands_api_key_for_a2a() -> None:
    """agent.yaml is authoritative, not the drifted per-agent conftest.

    a2a's integration conftest defaults API_KEY to 'not-needed'; agent.yaml
    lists it as required. Driving off agent.yaml makes this stricter.
    """
    with pytest.raises(MissingEnvError) as exc:
        build_env_map(
            A2A_AGENT,
            "ci-testing",
            container_image="img:latest",
            include_mlflow=False,
            environ={"BASE_URL": "https://llm", "MODEL_ID": "m"},
        )

    assert exc.value.missing == ["API_KEY"]


def test_build_env_map_includes_optional_vars_when_present() -> None:
    env_map = build_env_map(
        AGENTS_DIR / "autogen/templates/mcp_agent",
        "ci-testing",
        container_image="img:latest",
        include_mlflow=False,
        environ={
            "API_KEY": "k",
            "BASE_URL": "https://llm",
            "MODEL_ID": "m",
            "MCP_SERVER_URL": "https://mcp",
        },
    )

    assert env_map["MCP_SERVER_URL"] == "https://mcp"
    assert env_map["CONTAINER_IMAGE"] == "img:latest"


def test_build_env_map_never_forwards_port_or_container_image() -> None:
    env_map = build_env_map(
        REACT_AGENT,
        "ci-testing",
        container_image="img:latest",
        include_mlflow=False,
        environ={
            "API_KEY": "k",
            "BASE_URL": "https://llm",
            "MODEL_ID": "m",
            "PORT": "9999",
            "CONTAINER_IMAGE": "stale:image",
        },
    )

    assert "PORT" not in env_map
    assert env_map["CONTAINER_IMAGE"] == "img:latest"


def test_openai_agent_prefers_the_openai_vars() -> None:
    """QG7's env block is job-level, so QG4's per-matrix swap happens via aliases."""
    aliases = deploy_agents.ENV_SOURCE_ALIASES[
        "vanilla_python/templates/openai_responses_agent"
    ]
    env_map = build_env_map(
        AGENTS_DIR / "vanilla_python/templates/openai_responses_agent",
        "ci-testing",
        container_image="img:latest",
        include_mlflow=False,
        environ={
            "API_KEY": "cluster-key",
            "BASE_URL": "https://cluster-llm",
            "MODEL_ID": "cluster-model",
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_BASE_URL": "https://api.openai.test",
            "OPENAI_MODEL_ID": "gpt-x",
        },
        aliases=aliases,
    )

    assert env_map["API_KEY"] == "openai-key"
    assert env_map["BASE_URL"] == "https://api.openai.test"
    assert env_map["MODEL_ID"] == "gpt-x"


def test_absent_alias_does_not_fall_back_to_the_shared_endpoint() -> None:
    """Deliberately does NOT mirror QG4's `${{ matrix.BASE_URL || vars.BASE_URL }}`.

    That `||` is where the false green comes from: this agent talks to OpenAI, so
    silently substituting the cluster LLM makes the gate pass against an endpoint
    the agent is not meant to use. QG7 fails instead.
    """
    with pytest.raises(MissingEnvError) as exc:
        build_env_map(
            AGENTS_DIR / "vanilla_python/templates/openai_responses_agent",
            "ci-testing",
            container_image="img:latest",
            include_mlflow=False,
            environ={
                "API_KEY": "cluster-key",
                "BASE_URL": "https://cluster-llm",
                "MODEL_ID": "cluster-model",
            },
            aliases=deploy_agents.ENV_SOURCE_ALIASES[
                "vanilla_python/templates/openai_responses_agent"
            ],
        )

    assert exc.value.missing == ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL_ID"]


def test_build_env_map_adds_mlflow_block() -> None:
    env_map = build_env_map(
        REACT_AGENT,
        "ci-testing",
        container_image="img:latest",
        include_mlflow=True,
        deployment_name="langgraph-react-agent",
        environ={"API_KEY": "k", "BASE_URL": "https://llm", "MODEL_ID": "m"},
        **_MLFLOW_KWARGS,
    )

    assert env_map["MLFLOW_TRACKING_URI"] == "https://mlflow.example.test"
    assert env_map["MLFLOW_EXPERIMENT_NAME"] == "ci-testing/langgraph-react-agent"
    assert env_map["MLFLOW_WORKSPACE"] == "ci-testing"
    assert env_map["MLFLOW_TRACKING_INSECURE_TLS"] == "true"
    assert env_map["MLFLOW_TRACKING_TOKEN"] == "sha256~fake"


# ---------------------------------------------------------------------------
# mlflow_env
# ---------------------------------------------------------------------------


def test_experiment_name_is_unique_per_deployment() -> None:
    """A shared experiment name cross-contaminates traces (RHAIENG-6743)."""
    names = {
        mlflow_env("ci-testing", deployment, **_MLFLOW_KWARGS)["MLFLOW_EXPERIMENT_NAME"]
        for deployment in (
            "langgraph-react-agent",
            "crewai-websearch-agent",
            "a2a-langgraph-agent",
        )
    }

    assert len(names) == 3


# ---------------------------------------------------------------------------
# .env round trip
# ---------------------------------------------------------------------------


def test_write_env_file_stashes_and_restores_a_pre_existing_env(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("MINE=keep\n", encoding="utf-8")

    deploy_agents.write_env_file(tmp_path, {"API_KEY": "k"})
    assert (tmp_path / ".env").read_text() == "API_KEY=k\n"

    deploy_agents.remove_env_file(tmp_path)
    assert (tmp_path / ".env").read_text() == "MINE=keep\n"


def test_remove_env_file_leaves_nothing_behind(tmp_path: Path) -> None:
    deploy_agents.write_env_file(tmp_path, {"API_KEY": "k"})
    deploy_agents.remove_env_file(tmp_path)

    assert not (tmp_path / ".env").exists()
    assert list(tmp_path.iterdir()) == []


def test_write_env_file_quotes_awkward_values(tmp_path: Path) -> None:
    deploy_agents.write_env_file(tmp_path, {"MODEL_ID": "a b", "API_KEY": "x'y"})
    written = (tmp_path / ".env").read_text()

    sourced = subprocess.run(
        [
            "bash",
            "-c",
            f'set -a; source "{tmp_path / ".env"}"; printf "%s|%s" "$MODEL_ID" "$API_KEY"',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert sourced.stdout == "a b|x'y", written


# ---------------------------------------------------------------------------
# Deploy record — teardown reads this, not the selection
# ---------------------------------------------------------------------------


def test_deploy_record_round_trip(tmp_path: Path) -> None:
    record = deploy_btest_agents._DeployedRecord(tmp_path / "qg7-deployed.txt")
    record.reset()
    assert record.read() == []

    record.add("langgraph/templates/react_agent")
    record.add("crewai/templates/websearch_agent")

    assert record.read() == [
        "langgraph/templates/react_agent",
        "crewai/templates/websearch_agent",
    ]


def test_undeploy_is_a_noop_without_a_record(tmp_path: Path, monkeypatch) -> None:
    """The deploy pass truncates the record before doing anything, so no record
    means nothing was deployed."""
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    called = []
    monkeypatch.setattr(
        deploy_btest_agents, "undeploy_agent", lambda d: called.append(d)
    )

    assert deploy_btest_agents.run_undeploy([]) == 0
    assert called == []


def test_undeploy_skips_flow_import_agents(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    targets = select_agents(_targets(), [])
    langflow_id = "langflow/templates/simple_tool_calling_agent"

    record = deploy_btest_agents._DeployedRecord(tmp_path / "qg7-deployed.txt")
    record.reset()
    record.add(langflow_id)
    record.add("langgraph/templates/react_agent")

    called: list[Path] = []
    monkeypatch.setattr(
        deploy_btest_agents, "undeploy_agent", lambda d: called.append(Path(d))
    )
    monkeypatch.setattr(deploy_btest_agents, "remove_env_file", lambda d: None)

    assert deploy_btest_agents.run_undeploy(targets) == 0
    assert called == [AGENTS_DIR / "langgraph/templates/react_agent"]


# ---------------------------------------------------------------------------
# Tracing verification hints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("log_line", "expected"),
    [
        (
            "RESOURCE_DOES_NOT_EXIST: Workspace 'ci-testing' not found",
            "mlflow-tracking=enabled",
        ),
        ('401 {"error_code":"UNAUTHENTICATED"}', "MLflow operator"),
        ("Expecting value: line 1 column 1 (char 0)", "expired or invalid"),
        ("something else entirely", "no recognized failure pattern"),
    ],
)
def test_tracing_hints(log_line: str, expected: str) -> None:
    assert expected in deploy_agents._tracing_hint(log_line)


def _stub_logs(monkeypatch, pages: list[str]) -> list[float]:
    """Feed verify_tracing_enabled one log tail per call; record each sleep."""
    slept: list[float] = []
    remaining = list(pages)

    def fake_oc(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=remaining.pop(0) if remaining else pages[-1], stderr=""
        )

    monkeypatch.setattr(deploy_agents, "_oc", fake_oc)
    monkeypatch.setattr(deploy_agents.time, "sleep", slept.append)
    return slept


def test_tracing_marker_appearing_late_is_accepted(monkeypatch) -> None:
    # A rollout reports Ready before the app finishes logging, so the first
    # read can miss a marker that shows up seconds later.
    slept = _stub_logs(monkeypatch, ["starting up", "[Tracing Enabled] MLflow -> x"])

    deploy_agents.verify_tracing_enabled("react-agent", "ci-testing", poll_interval=1.0)

    assert slept == [1.0]


def test_tracing_failure_is_not_retried(monkeypatch) -> None:
    slept = _stub_logs(monkeypatch, ["[Tracing] Failed to configure: UNAUTHENTICATED"])

    with pytest.raises(deploy_agents.TracingNotEnabledError, match="MLflow operator"):
        deploy_agents.verify_tracing_enabled("react-agent", "ci-testing")

    assert slept == []


def test_tracing_falls_back_to_token_only_after_the_window(monkeypatch) -> None:
    slept = _stub_logs(monkeypatch, ["no marker here"])
    monkeypatch.setattr(deploy_agents, "_mlflow_server_reachable", lambda *a: True)

    deploy_agents.verify_tracing_enabled(
        "react-agent",
        "ci-testing",
        tracking_uri="https://mlflow.example/mlflow",
        token="t",
        startup_wait=0.3,
        poll_interval=0.1,
    )

    assert slept, "fallback must not fire on the first read"


def test_tracing_marker_tolerates_a2a_framework_tag(monkeypatch) -> None:
    # a2a logs `[Tracing Enabled LangGraph]`/`[Tracing Enabled CrewAI]`, so an
    # exact `[Tracing Enabled]` match never fires and both of its deployments
    # fall through to the weaker token-only check.
    _stub_logs(monkeypatch, ["[Tracing Enabled LangGraph] MLflow -> x, Experiment: e"])

    deploy_agents.verify_tracing_enabled("a2a-langgraph-agent", "ci-testing")


def test_tracing_failure_marker_tolerates_a2a_framework_tag(monkeypatch) -> None:
    _stub_logs(monkeypatch, ["[Tracing CrewAI] Failed to configure: UNAUTHENTICATED"])

    with pytest.raises(deploy_agents.TracingNotEnabledError, match="MLflow operator"):
        deploy_agents.verify_tracing_enabled("a2a-crew-agent", "ci-testing")


def test_deploy_agent_waits_for_the_rollout_before_probing(monkeypatch) -> None:
    # Without the wait, `make deploy` returns while the previous generation's
    # pod is still Ready and still serving the route, so a crash-looping new
    # image passes the readiness probe.
    calls: list[str] = []

    def fake_run_make(target, **kwargs):
        calls.append(f"make:{target}")

    def fake_oc(args, **kwargs):
        calls.append(f"oc:{' '.join(args[:2])}")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_get_route(name, namespace):
        calls.append(f"route:{name}")
        return f"https://{name}"

    monkeypatch.setattr(deploy_agents, "run_make", fake_run_make)
    monkeypatch.setattr(deploy_agents, "_oc", fake_oc)
    monkeypatch.setattr(deploy_agents, "get_route", fake_get_route)

    routes = deploy_agents.deploy_agent(
        AGENTS_DIR / "langgraph/templates/react_agent",
        "ci-testing",
        deployment_names=["langgraph-react-agent"],
    )

    assert routes == {"langgraph-react-agent": "https://langgraph-react-agent"}
    assert calls == [
        "make:build-openshift",
        "make:deploy",
        "oc:rollout status",
        "route:langgraph-react-agent",
    ]


def test_agentic_rag_prefers_the_ogx_endpoint() -> None:
    shared = {
        "API_KEY": "k",
        "BASE_URL": "http://vllm-svc:8000/v1",
        "MODEL_ID": "qwen2-5-7b-instruct",
        "EMBEDDING_MODEL": "e",
        "EMBEDDING_DIMENSION": "384",
        "VECTOR_STORE_PROVIDER": "milvus",
        "VECTOR_STORE_ID": "v",
    }
    aliases = deploy_agents.ENV_SOURCE_ALIASES["langgraph/templates/agentic_rag"]

    def env_map(environ):
        return build_env_map(
            AGENTS_DIR / "langgraph/templates/agentic_rag",
            "ci-testing",
            container_image="img:latest",
            include_mlflow=False,
            environ=environ,
            aliases=aliases,
        )

    aliased = env_map(
        {**shared, "OGX_BASE_URL": "http://ogx:8321/v1", "OGX_MODEL_ID": "vllm/qwen"}
    )
    assert aliased["BASE_URL"] == "http://ogx:8321/v1"
    assert aliased["MODEL_ID"] == "vllm/qwen"

    # An unset alias must NOT fall back to the shared value. The alias exists
    # because the shared endpoint is wrong for this agent, so falling back would
    # deploy against the vLLM service and pass -- a green gate testing the wrong
    # thing. Fail, naming the alias rather than the agent.yaml var.
    with pytest.raises(MissingEnvError) as exc:
        env_map(shared)
    assert exc.value.missing == ["OGX_BASE_URL", "OGX_MODEL_ID"]


def test_empty_alias_does_not_fall_back_to_the_shared_endpoint() -> None:
    """RHAIENG-7097: GitHub substitutes "" for an undefined variable, silently.

    Without this, openai_responses_agent runs against the cluster vLLM and passes.
    """
    with pytest.raises(MissingEnvError) as exc:
        build_env_map(
            AGENTS_DIR / "vanilla_python/templates/openai_responses_agent",
            "ci-testing",
            container_image="img:latest",
            include_mlflow=False,
            environ={
                "API_KEY": "shared-key",
                "BASE_URL": "http://vllm-svc:8000/v1",
                "MODEL_ID": "qwen2-5-7b-instruct",
                "OPENAI_API_KEY": "",
                "OPENAI_BASE_URL": "",
                "OPENAI_MODEL_ID": "",
            },
            aliases=deploy_agents.ENV_SOURCE_ALIASES[
                "vanilla_python/templates/openai_responses_agent"
            ],
        )

    assert exc.value.missing == ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL_ID"]


_ROUTES_JSON = """
{"items": [
  {"metadata": {"name": "data-science-gateway", "namespace": "openshift-ingress"},
   "spec": {"host": "rh-ai.apps.example.com"}},
  {"metadata": {"name": "mlflow", "namespace": "redhat-ods-applications"},
   "spec": {"host": "mlflow-redhat-ods-applications.apps.example.com"}},
  {"metadata": {"name": "rhods-dashboard", "namespace": "redhat-ods-applications"},
   "spec": {"host": "rhods-dashboard.apps.example.com"}}
]}
"""


def _stub_routes(monkeypatch, reachable: set[str]) -> None:
    def fake_oc(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=_ROUTES_JSON, stderr="")

    monkeypatch.setattr(deploy_agents, "_oc", fake_oc)
    monkeypatch.setattr(deploy_agents, "oc_token", lambda: "t")
    monkeypatch.setattr(
        deploy_agents, "_mlflow_server_reachable", lambda uri, token: uri in reachable
    )


def test_route_discovery_prefers_the_gateway_when_the_bare_route_404s(
    monkeypatch,
) -> None:
    # RHOAI 3.5 keeps a standalone `mlflow` route that answers 404; the tracking
    # server is behind the data-science gateway at /mlflow. Picking the 404 one
    # writes a dead URI into every agent's .env.
    _stub_routes(monkeypatch, {"https://rh-ai.apps.example.com/mlflow"})

    assert (
        deploy_agents._tracking_uri_from_route()
        == "https://rh-ai.apps.example.com/mlflow"
    )


def test_route_discovery_accepts_the_standalone_route_on_older_layouts(
    monkeypatch,
) -> None:
    standalone = "https://mlflow-redhat-ods-applications.apps.example.com"
    _stub_routes(monkeypatch, {standalone})

    assert deploy_agents._tracking_uri_from_route() == standalone


def test_route_discovery_ignores_unrelated_routes(monkeypatch) -> None:
    _stub_routes(monkeypatch, set())

    candidates = deploy_agents._tracking_uri_candidates()

    assert not any("rhods-dashboard" in c for c in candidates)
    assert candidates[0] == "https://rh-ai.apps.example.com/mlflow"


_FORBIDDEN_CRD = (
    'customresourcedefinitions.apiextensions.k8s.io "mlflowoperators.'
    'components.platform.opendatahub.io" is forbidden: User '
    '"system:serviceaccount:ci-testing:qg7-ci" cannot get resource '
    '"customresourcedefinitions" in API group "apiextensions.k8s.io" '
    "at the cluster scope"
)


def _stub_oc(monkeypatch, handler) -> list[list[str]]:
    """Route `_oc` through `handler`, recording every argv it sees."""
    seen: list[list[str]] = []

    def fake_oc(args, **kwargs):
        seen.append(list(args))
        return handler(list(args))

    monkeypatch.setattr(deploy_agents, "_oc", fake_oc)
    return seen


def test_operator_probe_reports_unknown_rather_than_absent_when_forbidden(
    monkeypatch,
) -> None:
    # CRDs are cluster-scoped. Collapsing "not permitted" into False claims
    # RHOAI < 3.5 on a 3.5 cluster and silently skips the namespace label.
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(args, 1, "", _FORBIDDEN_CRD),
    )

    assert deploy_agents.mlflow_operator_present() is None


def test_operator_probe_reports_absent_when_the_crd_is_genuinely_missing(
    monkeypatch,
) -> None:
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(
            args, 1, "", 'Error from server (NotFound): "..." not found'
        ),
    )

    assert deploy_agents.mlflow_operator_present() is False


def test_namespace_label_is_left_alone_when_forbidden_but_already_present(
    monkeypatch,
) -> None:
    def handler(args):
        if args[:2] == ["get", "crd"]:
            return subprocess.CompletedProcess(args, 1, "", _FORBIDDEN_CRD)
        if args[:2] == ["get", "namespace"]:
            return subprocess.CompletedProcess(args, 0, "enabled", "")
        raise AssertionError(f"unexpected oc call: {args}")

    seen = _stub_oc(monkeypatch, handler)

    assert deploy_agents.ensure_mlflow_namespace_label("ci-testing") is True
    assert not any(a[0] == "label" for a in seen), "should not attempt to relabel"


def test_namespace_label_raises_actionably_when_forbidden_and_absent(
    monkeypatch,
) -> None:
    # The false-green: skipping the label here leaves every agent to fail at
    # runtime with `Workspace not found`, long after the deploy gate went green.
    forbidden_label = (
        'namespaces "ci-testing" is forbidden: User "system:serviceaccount:'
        'ci-testing:qg7-ci" cannot patch resource "namespaces"'
    )

    def handler(args):
        if args[:2] == ["get", "crd"]:
            return subprocess.CompletedProcess(args, 1, "", _FORBIDDEN_CRD)
        if args[:2] == ["get", "namespace"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "label":
            return subprocess.CompletedProcess(args, 1, "", forbidden_label)
        raise AssertionError(f"unexpected oc call: {args}")

    _stub_oc(monkeypatch, handler)

    with pytest.raises(
        deploy_agents.MLflowConfigError, match="mlflow-tracking=enabled"
    ):
        deploy_agents.ensure_mlflow_namespace_label("ci-testing")


def test_route_discovery_yields_nothing_when_listing_routes_is_forbidden(
    monkeypatch,
) -> None:
    forbidden_routes = (
        "routes.route.openshift.io is forbidden: User "
        '"system:serviceaccount:ci-testing:qg7-ci" cannot list resource '
        '"routes" in API group "route.openshift.io" at the cluster scope'
    )
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(args, 1, "", forbidden_routes),
    )

    assert deploy_agents._tracking_uri_candidates() == []


# ---------------------------------------------------------------------------
# Token refresh subsystem (skill Step 4)
# ---------------------------------------------------------------------------


def _deployment_json(env_entries: list[dict]) -> str:
    """Minimal deployment JSON with the given env block."""
    return json.dumps(
        {
            "spec": {
                "template": {
                    "spec": {"containers": [{"name": "agent", "env": env_entries}]}
                }
            }
        }
    )


_SECRET_REF_ENV = [
    {
        "name": "MLFLOW_TRACKING_TOKEN",
        "valueFrom": {"secretKeyRef": {"name": "my-mlflow-secret", "key": "token"}},
    }
]
_HARDCODED_ENV = [{"name": "MLFLOW_TRACKING_TOKEN", "value": "sha256~literal"}]
_NO_TOKEN_ENV = [{"name": "API_KEY", "value": "k"}]


def test_mlflow_token_secret_name_returns_secret_ref(monkeypatch) -> None:
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(
            args, 0, _deployment_json(_SECRET_REF_ENV), ""
        ),
    )

    assert (
        deploy_agents.mlflow_token_secret_name("react-agent", "ci-testing")
        == "my-mlflow-secret"
    )


def test_mlflow_token_secret_name_raises_on_hardcoded_value(monkeypatch) -> None:
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(
            args, 0, _deployment_json(_HARDCODED_ENV), ""
        ),
    )

    with pytest.raises(HardcodedTokenError, match="literal value"):
        deploy_agents.mlflow_token_secret_name("react-agent", "ci-testing")


def test_mlflow_token_secret_name_returns_none_when_no_token_env(monkeypatch) -> None:
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(
            args, 0, _deployment_json(_NO_TOKEN_ENV), ""
        ),
    )

    assert deploy_agents.mlflow_token_secret_name("react-agent", "ci-testing") is None


def test_mlflow_token_secret_name_returns_none_on_missing_deployment(
    monkeypatch,
) -> None:
    _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(args, 1, "", "NotFound"),
    )

    assert deploy_agents.mlflow_token_secret_name("ghost", "ci-testing") is None


_EXISTING_SECRET = json.dumps(
    {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "my-mlflow-secret", "namespace": "ci-testing"},
        "data": {"other-key": "b3RoZXI="},
    }
)


def test_apply_token_to_secret_uses_helm_field_manager(monkeypatch) -> None:
    seen = _stub_oc(
        monkeypatch,
        lambda args: subprocess.CompletedProcess(
            args, 0, _EXISTING_SECRET if args[:2] == ["get", "secret"] else "", ""
        ),
    )

    deploy_agents._apply_token_to_secret("my-mlflow-secret", "ci-testing", "dG9rZW4=")

    apply_call = next(a for a in seen if a[0] == "apply")
    assert "--server-side" in apply_call
    assert "--field-manager=helm" in apply_call


def test_refresh_mlflow_token_deduplicates_shared_secrets(monkeypatch) -> None:
    applied: list[str] = []

    def handler(args):
        if args[:2] == ["get", "deployment"]:
            return subprocess.CompletedProcess(
                args, 0, _deployment_json(_SECRET_REF_ENV), ""
            )
        if args[:2] == ["get", "secret"]:
            return subprocess.CompletedProcess(args, 0, _EXISTING_SECRET, "")
        if args[0] == "apply":
            applied.append("apply")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["rollout", "restart"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["rollout", "status"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    _stub_oc(monkeypatch, handler)

    refreshed = deploy_agents.refresh_mlflow_token(
        "ci-testing",
        ["a2a-langgraph-agent", "a2a-crew-agent"],
        token="sha256~t",
    )

    assert refreshed == ["my-mlflow-secret"]
    assert len(applied) == 1


def test_refresh_mlflow_token_skips_deployment_without_secret_ref(
    monkeypatch,
) -> None:
    def handler(args):
        if args[:2] == ["get", "deployment"]:
            return subprocess.CompletedProcess(
                args, 0, _deployment_json(_NO_TOKEN_ENV), ""
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    _stub_oc(monkeypatch, handler)

    refreshed = deploy_agents.refresh_mlflow_token(
        "ci-testing", ["no-token-agent"], token="sha256~t"
    )

    assert refreshed == []
