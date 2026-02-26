#!/bin/bash
#
# Deploy LangGraph React Agent with Database Memory to OpenShift
#
# Usage:
#   ./deploy.sh
#
# Prerequisites:
#   - oc CLI installed and logged in to OpenShift cluster
#   - podman or docker installed
#   - Access to container registry (e.g., Quay.io)
#   - PostgreSQL database accessible from cluster
#

set -e  # Exit on error

source .env
export CONTAINER_IMAGE BASE_URL MODEL_ID POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD

## ============================================
# DOCKER BUILD
## ============================================

docker buildx build --platform linux/amd64 -t "${CONTAINER_IMAGE}" -f Dockerfile --push . && echo "Docker build completed"

## ============================================
# OPENSHIFT CREATE SECRETS
## ============================================

oc delete secret langgraph-db-memory-secrets --ignore-not-found && echo "Secrets deleted"
oc create secret generic langgraph-db-memory-secrets \
  --from-literal=api-key="${API_KEY}" \
  --from-literal=postgres-password="${POSTGRES_PASSWORD}" \
  && echo "Secrets created"

## ============================================
# OPENSHIFT DELETE DEPLOYMENT, SERVICE, ROUTE
## ============================================

oc delete deployment,service,route -l app=langgraph-db-memory --ignore-not-found && echo "Previous resources cleaned up"

## ============================================
# OPENSHIFT APPLY DEPLOYMENT, SERVICE, ROUTE
## ============================================
envsubst < k8s/deployment.yaml | oc apply -f - && echo "Deployment applied"
oc apply -f k8s/service.yaml && echo "Service applied"
oc apply -f k8s/route.yaml && echo "Route applied"

oc rollout status deployment/langgraph-db-memory --timeout=300s && echo "Deployment rolled out"

oc get deployment langgraph-db-memory && echo "Deployment exists"
oc get service langgraph-db-memory && echo "Service exists"
oc get route langgraph-db-memory && echo "Route exists"
