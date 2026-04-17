SHELL          := bash
AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
CHART_DIR      := ../../../charts/agent
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)

.PHONY: init run run-mcp interact-mcp build push build-openshift deploy deploy-mcp undeploy undeploy-mcp test dry-run dry-run-mcp help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

init: ## Copy .env.example to .env for configuration
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — edit it with your configuration"; else echo ".env already exists — skipping"; fi

run: ## Run agent locally with hot-reload (port 8000)
	@set -a && source .env && set +a && \
	  MCP_SERVER_URL="$${MCP_SERVER_URL:-http://127.0.0.1:8080/sse}" \
	  uv run uvicorn main:app --host 127.0.0.1 --port $${PORT:-8000} --reload --reload-exclude .venv

interact-mcp: ## Chat with MCP tools directly via LangGraph (no AutoGen agent)
	@set -a && source .env && set +a && \
	  cd mcp_automl_template && uv run python interact_with_mcp.py

run-mcp: ## Start MCP AutoML server locally (port 8080)
	@set -a && source .env && set +a && \
	  cd mcp_automl_template && PORT=8080 DISABLE_DNS_REBINDING_PROTECTION=true uv run python mcp_server.py

build: ## Build container image locally (podman/docker)
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; } && \
	  source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  cp -r ../../../images ./images && trap 'rm -rf ./images' EXIT && \
	  $(CONTAINER_CLI) build --platform linux/amd64 -t "$${CONTAINER_IMAGE}" -f Dockerfile .

push: ## Push container image to registry
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; } && \
	  source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  $(CONTAINER_CLI) push "$${CONTAINER_IMAGE}"

build-openshift: ## Build image in-cluster via OpenShift BuildConfig (no podman/docker needed)
	@cp -r ../../../images ./images && trap 'rm -rf ./images' EXIT && \
	  oc new-build --strategy=docker --binary --name=$(AGENT_NAME) --to=$(AGENT_NAME):latest 2>/dev/null || true && \
	  oc start-build $(AGENT_NAME) --from-dir=. --follow && \
	  NS=$$(oc project -q) && \
	  echo "" && \
	  echo "Image built. To deploy, set in .env:" && \
	  echo "  CONTAINER_IMAGE=image-registry.openshift-image-registry.svc:5000/$$NS/$(AGENT_NAME):latest"

_check-env:
	@set -a && source .env 2>/dev/null && set +a; \
	  missing=""; \
	  for var in $$(sed -n '/^ *required:/,/^ *[a-z]/{ /^ *- /s/^ *- *//p; }' agent.yaml); do \
	    eval val="\$$$$var"; \
	    [ -n "$$val" ] || missing="$$missing $$var"; \
	  done; \
	  [ -z "$$missing" ] || { echo "ERROR: Missing required env vars:$$missing"; exit 1; }

deploy: _check-env ## Deploy to OpenShift/K8s via Helm
	@source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  LAST_SEG="$${CONTAINER_IMAGE##*/}" && if [[ "$$LAST_SEG" == *:* ]]; then IMAGE_REPO="$${CONTAINER_IMAGE%:*}"; IMAGE_TAG="$${LAST_SEG##*:}"; else IMAGE_REPO="$${CONTAINER_IMAGE}"; IMAGE_TAG="latest"; fi && \
	  trap 'rm -f .helm-secrets.yaml' EXIT && \
	  umask 077 && \
	  printf 'secrets:\n  apiKey: "%s"\n' "$${API_KEY}" > .helm-secrets.yaml && \
	  helm upgrade --install $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    -f .helm-secrets.yaml \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" \
	    $${MCP_SERVER_URL:+--set env.MCP_SERVER_URL="$${MCP_SERVER_URL}"} && \
	  if command -v oc >/dev/null 2>&1; then \
	    echo "" && echo "Waiting for rollout to complete..." && \
	    if oc rollout status deployment/$(AGENT_NAME) --timeout=120s; then \
	      ROUTE=$$(oc get route $(AGENT_NAME) -o jsonpath='{.spec.host}' 2>/dev/null || true); \
	      if [ -n "$$ROUTE" ]; then echo "" && echo "Agent is available at: https://$$ROUTE"; fi; \
	    else \
	      echo "" && echo "WARNING: Rollout did not complete successfully. Check pod status with:" && \
	      echo "  oc get pods -l app.kubernetes.io/name=$(AGENT_NAME)" && \
	      echo "  oc logs deployment/$(AGENT_NAME)"; \
	    fi; \
	  fi

deploy-mcp: ## Build MCP AutoML server in-cluster and deploy via Helm
	@source .env 2>/dev/null || true && \
	  echo "--- Building MCP AutoML server in-cluster ---" && \
	  oc new-build --strategy=docker --binary --name=mcp-automl --to=mcp-automl:latest 2>/dev/null || true && \
	  oc start-build mcp-automl --from-dir=mcp_automl_template --follow && \
	  NS=$$(oc project -q) && \
	  MCP_IMAGE="image-registry.openshift-image-registry.svc:5000/$$NS/mcp-automl:latest" && \
	  echo "--- Deploying MCP AutoML server via Helm ---" && \
	  trap 'rm -f .helm-secrets-mcp.yaml' EXIT && \
	  umask 077 && \
	  printf 'extraSecrets:\n  DEPLOYMENT_TOKEN: "%s"\n' "$${DEPLOYMENT_TOKEN}" > .helm-secrets-mcp.yaml && \
	  helm upgrade --install mcp-automl $(CHART_DIR) \
	    -f mcp_automl_template/values.yaml \
	    -f .helm-secrets-mcp.yaml \
	    --set image.repository="$${MCP_IMAGE%:*}" \
	    --set image.tag="latest" \
	    $${DEPLOYMENT_URL:+--set env.DEPLOYMENT_URL="$${DEPLOYMENT_URL}"} && \
	  echo "" && echo "Waiting for rollout..." && \
	  if oc rollout status deployment/mcp-automl --timeout=120s; then \
	    ROUTE=$$(oc get route mcp-automl -o jsonpath='{.spec.host}' 2>/dev/null || true); \
	    if [ -n "$$ROUTE" ]; then echo "" && echo "MCP server deployed. The agent connects via in-cluster DNS (http://mcp-automl:8080/sse)." && echo "External URL (for debugging): https://$$ROUTE"; fi; \
	  fi

undeploy-mcp: ## Remove MCP AutoML server from cluster
	@helm uninstall mcp-automl || true
	@if command -v oc >/dev/null 2>&1; then \
	  oc delete buildconfig/mcp-automl imagestream/mcp-automl --ignore-not-found=true; \
	fi

dry-run-mcp: ## Preview MCP AutoML server Helm templates
	@source .env 2>/dev/null || true && \
	  helm template mcp-automl $(CHART_DIR) \
	    -f mcp_automl_template/values.yaml \
	    --set image.repository="placeholder" \
	    --set extraSecrets.DEPLOYMENT_TOKEN="REDACTED" \
	    $${DEPLOYMENT_URL:+--set env.DEPLOYMENT_URL="$${DEPLOYMENT_URL}"}

dry-run: _check-env ## Render Helm templates without deploying
	@source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  LAST_SEG="$${CONTAINER_IMAGE##*/}" && if [[ "$$LAST_SEG" == *:* ]]; then IMAGE_REPO="$${CONTAINER_IMAGE%:*}"; IMAGE_TAG="$${LAST_SEG##*:}"; else IMAGE_REPO="$${CONTAINER_IMAGE}"; IMAGE_TAG="latest"; fi && \
	  helm template $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    --set secrets.apiKey="REDACTED" \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" \
	    $${MCP_SERVER_URL:+--set env.MCP_SERVER_URL="$${MCP_SERVER_URL}"}

undeploy: ## Remove agent deployment from cluster (does NOT remove MCP server)
	helm uninstall $(AGENT_NAME)

test: ## Run tests
	uv run --extra dev python -m pytest tests/
