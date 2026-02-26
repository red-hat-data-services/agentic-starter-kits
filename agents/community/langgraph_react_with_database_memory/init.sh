#!/bin/bash
# Usage:
#   ./init.sh
#
# Prerequisites:
#   - oc CLI installed and logged in to OpenShift cluster
#   - docker installed
#   - Access to container registry (e.g., Quay.io)
#   - PostgreSQL database configured
#

set -e

source .env && echo "Environment variables loaded from .env file"

# Check LLM configuration
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

if [ -z "$CONTAINER_IMAGE" ]; then
    echo "CONTAINER_IMAGE not set, check .env file"
    exit 1
fi

# Check PostgresSQL configuration
if [ -z "$POSTGRES_HOST" ]; then
    echo "POSTGRES_HOST not set, check .env file"
    exit 1
fi

if [ -z "$POSTGRES_PORT" ]; then
    echo "POSTGRES_PORT not set, check .env file"
    exit 1
fi

if [ -z "$POSTGRES_DB" ]; then
    echo "POSTGRES_DB not set, check .env file"
    exit 1
fi

if [ -z "$POSTGRES_USER" ]; then
    echo "POSTGRES_USER not set, check .env file"
    exit 1
fi

if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "POSTGRES_PASSWORD not set, check .env file"
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the root directory of the repository (3 levels up from script)
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Copy utils.py to the destination
cp "$ROOT_DIR/utils.py" "$SCRIPT_DIR/src/langgraph_react_with_database_memory/" && echo "Utils.py copied to destination"

echo "Agent initialized successfully"
echo "Configuration validated:"
echo "  LLM: $BASE_URL / $MODEL_ID"
echo "  Database: postgresql://$POSTGRES_USER@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"
