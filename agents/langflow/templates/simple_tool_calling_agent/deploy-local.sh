#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$SCRIPT_DIR/local"

echo "=== Langflow Simple Tool Calling Agent - Local Deployment ==="
echo ""

# Check podman
if ! command -v podman &>/dev/null; then
  echo "ERROR: Podman is not installed."
  echo "  macOS: brew install podman podman-compose && podman machine init && podman machine start"
  echo "  Linux: sudo dnf install -y podman && pip install podman-compose"
  exit 1
fi

if ! command -v podman-compose &>/dev/null; then
  echo "ERROR: podman-compose is not installed. Install with: pip install podman-compose"
  exit 1
fi

# Ensure init has been run
if [ ! -f "$LOCAL_DIR/.env" ]; then
  echo "ERROR: local/.env not found. Run 'make init' first."
  exit 1
fi

cd "$LOCAL_DIR" || { echo "ERROR: Directory $LOCAL_DIR not found."; exit 1; }

# Start containerized services (Langflow, PostgreSQL, Langfuse)
echo ""
echo "Starting local stack (Langflow + PostgreSQL + Langfuse v3 + ClickHouse + MinIO + Redis)..."
podman-compose up -d

echo ""
echo "Waiting for Langflow to start (this may take a few minutes)..."
LANGFLOW_READY=false
for i in $(seq 1 60); do
  if curl -s http://localhost:7860/health >/dev/null 2>&1; then
    LANGFLOW_READY=true
    echo "Langflow is ready!"
    break
  fi
  sleep 5
done

if [ "$LANGFLOW_READY" = false ]; then
  echo "ERROR: Langflow did not start within 5 minutes."
  echo "Check logs: podman logs local_langflow_1"
  exit 1
fi

echo ""
echo "Waiting for Langfuse to start (this may take several minutes)..."
LANGFUSE_READY=false
for i in $(seq 1 60); do
  if curl -s http://localhost:3000/api/public/health >/dev/null 2>&1; then
    LANGFUSE_READY=true
    echo "Langfuse is ready!"
    break
  fi
  sleep 10
done

if [ "$LANGFUSE_READY" = false ]; then
  echo "WARNING: Langfuse did not start within 10 minutes. Tracing and logging will not work until it is up."
  echo "Check logs: podman logs local_langfuse-web_1"
fi

echo ""
echo "=== Local environment is ready ==="
echo ""
echo "  Langflow UI:  http://localhost:7860"
echo "  Langfuse:     http://localhost:3000  (login: admin@langflow.local / password auto-generated in local/.env)"
echo ""
echo "  Next steps:"
echo "    1. Open http://localhost:7860"
echo "    2. Import the flow: flows/outdoor-activity-agent.json"
echo "    3. Configure the flow components (see README for details):"
echo "       - KServe vLLM: set api_base and model_name (Ollama, LlamaStack, or remote endpoint)"
echo "       - NPS Search Parks: set api_key (get one at https://developer.nps.gov)"
echo "       - NPS Park Alerts: set api_key (same NPS key)"
echo "    4. Run the agent from the Langflow UI"
echo ""
echo "  To stop:              make stop"
echo "  To stop and wipe data: make clean"
