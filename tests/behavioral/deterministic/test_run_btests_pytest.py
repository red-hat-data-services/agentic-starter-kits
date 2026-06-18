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
