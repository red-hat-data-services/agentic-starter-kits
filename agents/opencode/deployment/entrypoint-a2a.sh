#!/bin/bash
# Entrypoint for OpenCode A2A container
#
# Runs two processes:
# 1. opencode serve (background) - OpenCode HTTP API on port 4096
# 2. opencode-a2a (foreground) - A2A agent card server on port 8000
#
# Environment variables (Kagenti standard names):
#   LLM_API_BASE  - LLM API endpoint (e.g., https://api.openai.com/v1)
#   LLM_API_KEY   - API key for the LLM provider (optional)
#   LLM_MODEL     - Model identifier (e.g., gpt-4o)

set -e

echo "Starting OpenCode A2A container..."

# Translate Kagenti-standard LLM_* env vars to OpenCode configuration
# Kagenti standard: LLM_API_BASE, LLM_API_KEY, LLM_MODEL
# OpenCode needs: Full provider configuration in opencode.json
if [[ -n "${LLM_API_BASE}" || -n "${LLM_MODEL}" ]]; then
    echo "Configuring OpenCode from Kagenti LLM_* environment variables..."

    CONFIG_DIR="${HOME}/.config/opencode"
    mkdir -p "${CONFIG_DIR}"

    # Set defaults if not provided
    PROVIDER_NAME="${LLM_PROVIDER:-vllm}"
    BASE_URL="${LLM_API_BASE:-}"
    API_KEY="${LLM_API_KEY:-}"
    MODEL_NAME="${LLM_MODEL:-gpt-4o}"

    # Validate required fields
    if [[ -z "${BASE_URL}" ]]; then
        echo "ERROR: LLM_API_BASE is required when generating OpenCode configuration"
        echo "Please set the LLM_API_BASE environment variable to your LLM API endpoint"
        exit 1
    fi

    echo "  Provider: ${PROVIDER_NAME}, Model: ${MODEL_NAME}"

    # Generate full OpenCode provider config (following msager-opencode reference)
    # Use umask 077 to ensure config file is created with 0600 permissions (owner-only read/write)
    # since it contains sensitive API key
    (umask 077 && cat > "${CONFIG_DIR}/opencode.json" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "${PROVIDER_NAME}": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "${PROVIDER_NAME}",
      "options": {
        "baseURL": "${BASE_URL}",
        "apiKey": "${API_KEY}"
      },
      "models": {
        "${MODEL_NAME}": {
          "name": "${MODEL_NAME}"
        }
      }
    }
  },
  "model": "${PROVIDER_NAME}/${MODEL_NAME}",
  "small_model": "${PROVIDER_NAME}/${MODEL_NAME}",
  "enabled_providers": ["${PROVIDER_NAME}"]
}
EOF
    )
    echo "  Config written to ${CONFIG_DIR}/opencode.json"
fi

# Start opencode serve in background
echo "Starting opencode serve on port 4096..."
opencode serve &
OPENCODE_PID=$!

# Cleanup function for background opencode serve process
cleanup() {
    echo 'Shutting down opencode serve...'
    kill $OPENCODE_PID 2>/dev/null
    wait $OPENCODE_PID 2>/dev/null
}

# Set up traps to cleanly shutdown background process
# EXIT trap: cleanup on normal exit or crash (preserves exit code)
# TERM trap: cleanup on SIGTERM, exit 143 (128 + 15)
# INT trap: cleanup on SIGINT, exit 130 (128 + 2)
trap cleanup EXIT
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 130' INT

# Wait for opencode serve to be ready
echo "Waiting for opencode serve to be ready..."
for i in {1..30}; do
    if curl -sf http://127.0.0.1:4096/health >/dev/null 2>&1; then
        echo "opencode serve is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Warning: opencode serve health check timed out, continuing anyway..."
    fi
    sleep 1
done

# Run opencode-a2a in foreground (shell remains PID 1 for trap handling)
echo "Starting opencode-a2a on port 8000..."
opencode-a2a \
    --port "${A2A_PORT:-8000}" \
    --opencode-url "${OPENCODE_BASE_URL:-http://127.0.0.1:4096}"
