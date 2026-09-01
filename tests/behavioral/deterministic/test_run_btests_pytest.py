from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("run-btests-pytest.sh")


def _run_bash(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        cwd=SCRIPT_PATH.parent,
    )


def test_resolve_test_path_prefers_templates_layout_for_react_agent() -> None:
    result = _run_bash(
        f'BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}"; resolve_test_path "langgraph/templates/react_agent"'
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (
        result.stdout.strip()
        == "agents/langgraph/templates/react_agent/tests/behavioral/"
    )


def test_resolve_test_path_supports_autogen_templates_layout() -> None:
    result = _run_bash(
        f'BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}"; resolve_test_path "autogen/templates/mcp_agent"'
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (
        result.stdout.strip() == "agents/autogen/templates/mcp_agent/tests/behavioral/"
    )


def test_selected_agent_run_does_not_fail_conftest_sync_check() -> None:
    result = _run_bash(
        f'''BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}";
AGENTS=("langgraph/templates/react_agent|REACT_AGENT_URL|langgraph-react-agent");
validate_agent_url_map_sync'''
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_detect_cluster_domain_is_non_fatal_when_namespace_has_no_routes() -> None:
    result = _run_bash(
        f'''BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}";
timeout() {{ shift; "$@"; }}
oc() {{ return 0; }}
NAMESPACE=ci-testing
cluster_domain="$(detect_cluster_domain)"
rc=$?
printf 'rc=%s\\nout=%s\\n' "$rc" "$cluster_domain"'''
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "rc=0" in result.stdout
    assert "out=" in result.stdout


def test_is_flow_import_detects_langflow_agent() -> None:
    result = _run_bash(
        f'BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}"; '
        'is_flow_import "langflow/templates/simple_tool_calling_agent" && echo "yes" || echo "no"'
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "yes"


def test_is_flow_import_rejects_standard_agent() -> None:
    result = _run_bash(
        f'BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}"; '
        'is_flow_import "langgraph/templates/react_agent" && echo "yes" || echo "no"'
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "no"


def test_preflight_uses_route_health_check_for_flow_import_agent() -> None:
    result = _run_bash(
        f'''BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}";
timeout() {{ shift; "$@"; }}
oc() {{
  if [[ "$1" == "whoami" ]]; then echo "ci-user"; return 0; fi
  if [[ "$1" == "project" ]]; then echo "ci-ns"; return 0; fi
  if [[ "$1" == "get" && "$2" == "route" ]]; then echo "langflow.apps.test.example.com"; return 0; fi
  if [[ "$1" == "get" && "$2" == "routes" ]]; then return 0; fi
  return 1
}}
curl() {{ return 0; }}
uv() {{ echo "LANGFLOW_TOOL_CALLING_AGENT_URL"; }}
command() {{ return 0; }}
AGENTS=("langflow/templates/simple_tool_calling_agent|LANGFLOW_TOOL_CALLING_AGENT_URL|langflow|langflow-agent")
preflight 2>&1'''
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "flow-import" in result.stdout


def test_detect_mlflow_config_skips_when_all_agents_are_flow_import() -> None:
    result = _run_bash(
        f'''BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}";
timeout() {{ shift; "$@"; }}
oc() {{ return 1; }}
AGENTS=("langflow/templates/simple_tool_calling_agent|LANGFLOW_TOOL_CALLING_AGENT_URL|langflow|langflow-agent")
detect_mlflow_config 2>&1'''
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Skipping MLflow detection" in result.stdout


def test_main_rejects_legacy_agent_id_without_templates_segment() -> None:
    result = _run_bash(
        f'''BTEST_LIB_ONLY=1 source "{SCRIPT_PATH}";
preflight() {{ :; }}
detect_mlflow_config() {{ :; }}
run_tests() {{ printf '%s\\n' "${{AGENTS[@]}}"; }}
print_summary() {{ :; }}
main langgraph/react_agent'''
    )

    assert result.returncode == 1, result.stderr or result.stdout
    assert "Unknown agent: langgraph/react_agent" in result.stdout
    assert "langgraph/templates/react_agent" in result.stdout
