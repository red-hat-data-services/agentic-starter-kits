#!/bin/bash
#
# Deploy LangGraph Agentic RAG to OpenShift
#
# Usage:
#   ./deploy.sh
#
# Prerequisites:
#   - oc CLI installed and logged in to OpenShift cluster
#   - podman or docker installed
#   - Access to container registry (e.g., Quay.io)
#

set -e  # Exit on error

source .env
export CONTAINER_IMAGE BASE_URL MODEL_ID EMBEDDING_MODEL

## ============================================
# DOCKER BUILD
## ============================================

docker buildx build --platform linux/amd64 -t "${CONTAINER_IMAGE}" -f Dockerfile --push . && echo "Docker build completed"

## ============================================
# OPENSHIFT CREATE SECRET
## ============================================

oc delete secret langgraph-agentic-rag-secrets --ignore-not-found && echo "Secret deleted"
oc create secret generic langgraph-agentic-rag-secrets --from-literal=api-key="${API_KEY}" && echo "Secret created"

## ============================================
# OPENSHIFT DELETE DEPLOYMENT, SERVICE, ROUTE
## ============================================

oc delete deployment,service,route -l app=langgraph-agentic-rag --ignore-not-found && echo "Previous resources cleaned up"

## ============================================
# OPENSHIFT APPLY DEPLOYMENT, SERVICE, ROUTE
## ============================================
envsubst < k8s/deployment.yaml | oc apply -f - && echo "Deployment applied"
oc apply -f k8s/service.yaml && echo "Service applied"
oc apply -f k8s/route.yaml && echo "Route applied"

oc rollout status deployment/langgraph-agentic-rag --timeout=300s && echo "Deployment rolled out"

oc get deployment langgraph-agentic-rag && echo "Deployment exists"
oc get service langgraph-agentic-rag && echo "Service exists"
oc get route langgraph-agentic-rag && echo "Route exists"