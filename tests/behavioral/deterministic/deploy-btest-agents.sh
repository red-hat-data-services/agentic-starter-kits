#!/usr/bin/env bash
# deploy-btest-agents.sh — Deploy/tear down the QG7 btest agent set.
#
# Usage:  ./deploy-btest-agents.sh                        # deploy the full set
#         ./deploy-btest-agents.sh langgraph/templates/react_agent
#         ./deploy-btest-agents.sh --print-selection      # effective ids, one per line
#         ./deploy-btest-agents.sh --undeploy             # tear down what was deployed
#
# QG7's runner (run-btests-pytest.sh) assumes agents are already deployed,
# healthy, and tracing to MLflow. Nothing in CI satisfied that, so this script
# gives the gate its own deploy/teardown.
#
# This wrapper exists because the agent set *is* a bash array: it sources the
# runner under BTEST_LIB_ONLY=1 to read AGENTS, then hands the tuples to the
# Python entrypoint. Deploy and test therefore can never drift on the agent set.
#
# Requirements: oc, helm, uv

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Source the runner as a library to pick up its AGENTS array.
BTEST_LIB_ONLY=1 source "${SCRIPT_DIR}/run-btests-pytest.sh"

QG7_AGENT_CONFIG="$(printf '%s\n' "${AGENTS[@]}")"
export QG7_AGENT_CONFIG

# integration.utils lives under tests/, mirroring what the agent Makefiles
# export for their own integration targets.
export PYTHONPATH="${REPO_ROOT}/tests${PYTHONPATH:+:${PYTHONPATH}}"

cd "${REPO_ROOT}"
exec uv run --extra test python \
  "${SCRIPT_DIR}/deploy_btest_agents.py" "$@"
