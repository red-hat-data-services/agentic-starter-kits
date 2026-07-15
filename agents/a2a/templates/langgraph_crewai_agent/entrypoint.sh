#!/bin/sh
# Chooses which A2A server to run (same image, two Deployment variants).
set -e
export PORT="${PORT:-8080}"
export HOME="${HOME:-/home/appuser}"
case "${A2A_ROLE:-crew}" in
  crew)
    exec python -m a2a_langgraph_crewai.crew_a2a_server
    ;;
  langgraph)
    exec python -m a2a_langgraph_crewai.langgraph_a2a_server
    ;;
  *)
    echo "A2A_ROLE must be 'crew' or 'langgraph', got: ${A2A_ROLE}" >&2
    exit 1
    ;;
esac
