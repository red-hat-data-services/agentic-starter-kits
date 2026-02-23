#!/bin/bash
#
# Initialize the OpenAI Responses Agent
#
# Usage:
#   ./init.sh
#
# Prerequisites:
#   - oc CLI installed and logged in to OpenShift cluster
#   - docker installed
#   - Access to container registry (e.g., Quay.io)
#

set -e

source .env && echo "Environment variables loaded from .env file"

if [ -z "$CONTAINER_IMAGE" ]; then
    echo "CONTAINER_IMAGE not set, check .env file"
    exit 1
fi
if [ -z "$API_KEY" ]; then
    echo "API_KEY not set, check .env file"
    exit 1
fi

if [ -z "$BASE_URL" ]; then
    echo "BASE_URL not set, check .env file"
    exit 1
fi

if [ -z "$MODEL_ID" ]; then
    echo "MODEL_ID not set, check .env file"
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the root directory of the repository (3 levels up from script)
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Copy utils.py to the destination (if present at repo root)
if [ -f "$ROOT_DIR/utils.py" ]; then
    cp "$ROOT_DIR/utils.py" "$SCRIPT_DIR/src/openai_responses_agent_base/" && echo "utils.py copied to destination"
fi

echo "Agent initialized successfully"
