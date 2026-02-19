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
#

set -e

echo "Initializing LangGraph Agentic RAG Agent..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "Please edit .env file with your configuration"
else
    echo ".env file already exists"
fi

# Load environment variables
source .env && echo "Environment variables loaded from .env file"

# Check required variables
if [ -z "$BASE_URL" ]; then
    echo "BASE_URL not set, check .env file"
    exit 1
fi

if [ -z "$MODEL_ID" ]; then
    echo "MODEL_ID not set, check .env file"
    exit 1
fi

# Create data directory for vector store if specified
if [ -n "$VECTOR_STORE_PATH" ]; then
    mkdir -p "$(dirname "$VECTOR_STORE_PATH")" && echo "Vector store directory created"
fi

# Install dependencies
echo "Installing dependencies..."
if command -v poetry &> /dev/null; then
    echo "Using poetry to install dependencies..."
    poetry install
else
    echo "Using pip to install dependencies..."
    pip install -r requirements.txt
fi

echo ""
echo "Agent initialized successfully!"
echo ""
echo "To start the agent, run:"
echo "  python main.py"
echo ""