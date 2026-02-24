#!/bin/bash
#
# Initialize the LangGraph Agentic RAG Agent
#
# Usage:
#   ./init.sh
#
# Prerequisites:
#   - Python 3.10+ installed
#   - pip or poetry installed

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

# Copy utils.py to the destination
cp "$ROOT_DIR/utils.py" "$SCRIPT_DIR/src/langgraph_agentic_rag/" && echo "Utils.py copied to destination"

echo "Agent initialized successfully"
