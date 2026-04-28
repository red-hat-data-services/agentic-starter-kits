SHELL          := bash
AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
CHART_DIR      := ../../../charts/agent
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
MODEL          ?= llama3.1:8b

.PHONY: init re-init env ollama llama-server run-app run-app-fresh run-cli build push build-openshift deploy undeploy test dry-run help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

re-init: ## Activate venv and reload .env variables
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "Venv activated and .env variables loaded."

init: ## Copy .env.example to .env for configuration
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — edit it with your configuration"; else echo ".env already exists — skipping"; fi

env: ## Create venv, load .env, and install dependencies
	@echo "==> Creating virtual environment and installing dependencies..." && \
	  rm -rf .venv && \
	  uv sync --python 3.12 && \
	  echo "==> Load .env variables..." && \
	  source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "" && \
	  echo "Done. Next steps:" && \
	  echo "  make ollama   # install Ollama and pull models" && \
	  echo "  make llama-server    # start Llama Stack server"

ollama: ## Install Ollama, start it, and pull models
	@source .venv/bin/activate && set -a && source .env && set +a && \
	if command -v ollama >/dev/null 2>&1; then \
	  echo "==> Ollama already installed, skipping..."; \
	else \
	  echo "==> Installing Ollama..." && \
	  curl -fsSL https://ollama.com/install.sh | sh; \
	fi && \
	  echo "==> Starting Ollama service..." && \
	  ollama serve &>/dev/null & \
	  OLLAMA_PID=$$! && \
	  echo "Waiting for Ollama to be ready (max 30s)..." && \
	  OLLAMA_WAIT=0 && \
	  until ollama list >/dev/null 2>&1; do \
	    OLLAMA_WAIT=$$((OLLAMA_WAIT + 1)); \
	    if [ $$OLLAMA_WAIT -ge 30 ]; then \
	      echo "ERROR: Ollama failed to start within 30 seconds." && \
	      kill $$OLLAMA_PID 2>/dev/null; \
	      exit 1; \
	    fi; \
	    sleep 1; \
	  done && \
	  echo "==> Pulling $(MODEL)..." && \
	  ollama pull $(MODEL) && \
	  echo "==> Creating Milvus dir..." && \
	  mkdir -p ../../../milvus_data && \
	  echo "" && \
	  echo "Done. Run 'make llama-server' to start the Llama Stack server."

llama-server: ## Install llama-stack and start Llama Stack server
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "==> Installing llama-stack..." && \
	  uv pip install "llama-stack==0.5.0" "llama-stack-api==0.5.0" ollama && \
	  echo "==> Killing any existing process on port 8321..." && \
	  lsof -ti:8321 | xargs kill -9 2>/dev/null; true && \
	  echo "==> Starting Llama Stack server on port 8321..." && \
	  llama stack run ../../../run_llama_server.yaml

run-app: ## Run agent locally with hot-reload
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  if lsof -ti:$${PORT:-8000} >/dev/null 2>&1; then \
	    echo "ERROR: Port $${PORT:-8000} is already in use." && \
	    echo "  Change PORT in .env or run: make run-app-fresh" && \
	    exit 1; \
	  fi && \
	  uv run uvicorn main:app --host 127.0.0.1 --port $${PORT:-8000} --reload --reload-exclude .venv

run-app-fresh: ## Kill existing process on port and run agent with hot-reload
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "==> Killing existing process on port $${PORT:-8000}..." && \
	  lsof -ti:$${PORT:-8000} | xargs kill -9 2>/dev/null; true && \
	  uv run uvicorn main:app --host 127.0.0.1 --port $${PORT:-8000} --reload --reload-exclude .venv

run-cli: ## Run interactive CLI chat (no web server)
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  cd examples && uv run python execute_ai_service_locally.py

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
	  case "$${CONTAINER_IMAGE}" in *:*) IMAGE_REPO="$${CONTAINER_IMAGE%:*}"; IMAGE_TAG="$${CONTAINER_IMAGE##*:}";; *) IMAGE_REPO="$${CONTAINER_IMAGE}"; IMAGE_TAG="latest";; esac && \
	  trap 'rm -f .helm-secrets.yaml' EXIT && \
	  umask 077 && \
	  printf 'secrets:\n  apiKey: "%s"\n' "$${API_KEY}" > .helm-secrets.yaml && \
	  helm upgrade --install $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    -f .helm-secrets.yaml \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" && \
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

dry-run: _check-env ## Render Helm templates without deploying
	@source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  case "$${CONTAINER_IMAGE}" in *:*) IMAGE_REPO="$${CONTAINER_IMAGE%:*}"; IMAGE_TAG="$${CONTAINER_IMAGE##*:}";; *) IMAGE_REPO="$${CONTAINER_IMAGE}"; IMAGE_TAG="latest";; esac && \
	  helm template $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    --set secrets.apiKey="REDACTED" \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}"

undeploy: ## Remove deployment from cluster
	helm uninstall $(AGENT_NAME)

test: ## Run tests
	uv run --extra dev python -m pytest tests/
