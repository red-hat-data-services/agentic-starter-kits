#!/usr/bin/env bash
# Cleanup script — keeps going on errors to clean up as much as possible
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$SCRIPT_DIR/local"

cd "$LOCAL_DIR" || { echo "ERROR: Directory $LOCAL_DIR not found."; exit 1; }

if [ "${1:-}" = "--force" ]; then
  echo "Stopping services and removing all data..."
  # Stop containerized services
  podman-compose down --remove-orphans -v -t 5 || true
  # Force kill and remove any lingering containers from this compose project
  for c in $(podman ps -a --filter "label=io.podman.compose.project=local" -q 2>/dev/null); do
    podman rm -f "$c" || true
  done
  # Remove project volumes
  for v in $(podman volume ls --filter "label=io.podman.compose.project=local" -q 2>/dev/null); do
    podman volume rm -f "$v" || true
  done
  # Remove project network
  podman network rm local_default || true
  # Clean up config
  rm -f "$LOCAL_DIR/.env"
  echo "Done. All services stopped and data removed."
else
  echo "Stopping services (data preserved)..."
  podman-compose down --remove-orphans || true
  echo "Done. Run 'make run' to start again."
fi
