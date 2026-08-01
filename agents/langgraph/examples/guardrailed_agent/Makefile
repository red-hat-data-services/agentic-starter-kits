SHELL          := bash
AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
CHART_DIR      := ../../deployment
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
MODEL          ?= llama3.1:8b

.PHONY: init re-init env ollama run-app run-app-fresh build push build-openshift deploy undeploy test test-guardrails-integration test-guardrails-integration-nemoguard test-integration dry-run help guardrails-server-local guardrails-server-nemoguard

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

re-init: ## Activate venv and reload .env variables
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "Venv activated and .env variables loaded."

init: ## Copy .env.example to .env for configuration
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example - edit it with your configuration"; else echo ".env already exists - skipping"; fi

env: ## Create venv, load .env, and install dependencies (including NeMo Guardrails)
	@echo "==> Creating virtual environment and installing dependencies..." && \
	  rm -rf .venv && \
	  uv sync --python 3.12 --extra guardrails && \
	  echo "==> Load .env variables..." && \
	  source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "" && \
	  echo "Done. Next steps:" && \
	  echo "  make ollama                       # install Ollama and pull models" && \
	  echo "  make guardrails-server-local      # start NeMo Guardrails proxy (self-check, Ollama)" && \
	  echo "  make guardrails-server-nemoguard  # start NeMo Guardrails proxy (layered NemoGuard models)" && \
	  echo "  make run-app                      # start the agent"

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
	  echo "" && \
	  echo "Done. Run 'make guardrails-server-local' to start NeMo Guardrails."

guardrails-server-local: ## Generate local (self-check, Ollama) config and start NeMo Guardrails proxy
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  cp guardrails/config/local/config.yaml.example guardrails/config/local/config.yaml && \
	  python3 guardrails/generate_config.py --profile local && \
	  echo "Starting NeMo Guardrails server (local profile) on port $${GUARDRAILS_PORT:-8090}..." && \
	  nemoguardrails server --config guardrails/config --default-config-id local --port $${GUARDRAILS_PORT:-8090} --disable-chat-ui

guardrails-server-nemoguard: ## Generate layered NemoGuard-models config and start NeMo Guardrails proxy
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  cp guardrails/config/nemoguard/config.yaml.example guardrails/config/nemoguard/config.yaml && \
	  python3 guardrails/generate_config.py --profile nemoguard && \
	  echo "Starting NeMo Guardrails server (nemoguard profile) on port $${GUARDRAILS_PORT:-8090}..." && \
	  nemoguardrails server --config guardrails/config --default-config-id nemoguard --port $${GUARDRAILS_PORT:-8090} --disable-chat-ui

run-app: ## Run agent locally with hot-reload
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  if lsof -ti:$${PORT:-8000} >/dev/null 2>&1; then \
	    echo "ERROR: Port $${PORT:-8000} is already in use." && \
	    echo "  Change PORT in .env or run: make run-app-fresh" && \
	    exit 1; \
	  fi && \
	  uv run $${MLFLOW_TRACKING_URI:+--extra tracing} uvicorn main:app --host 127.0.0.1 --port $${PORT:-8000} --reload --reload-exclude .venv

run-app-fresh: ## Kill existing process on port and run agent with hot-reload
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "==> Killing existing process on port $${PORT:-8000}..." && \
	  lsof -ti:$${PORT:-8000} | xargs kill -9 2>/dev/null; true && \
	  uv run $${MLFLOW_TRACKING_URI:+--extra tracing} uvicorn main:app --host 127.0.0.1 --port $${PORT:-8000} --reload --reload-exclude .venv

build: ## Build container image locally (podman/docker)
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; } && \
	  source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  cp -r ../../../../images ./images && \
	  mkdir -p ./components && cp -r ../../../../components/auth ./components/auth && \
	  trap 'rm -rf ./images ./components/auth; rmdir ./components 2>/dev/null || true' EXIT && \
	  $(CONTAINER_CLI) build --platform linux/amd64 -t "$${CONTAINER_IMAGE}" -f Dockerfile .

push: ## Push container image to registry
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; } && \
	  source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  $(CONTAINER_CLI) push "$${CONTAINER_IMAGE}"

build-openshift: ## Build image in-cluster via OpenShift BuildConfig (no podman/docker needed)
	@cp -r ../../../../images ./images && \
	  mkdir -p ./components && cp -r ../../../../components/auth ./components/auth && \
	  trap 'rm -rf ./images ./components/auth; rmdir ./components 2>/dev/null || true' EXIT && \
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
	  AUTH_ALLOWLIST="$${AUTH_ALLOWED_SERVICEACCOUNTS:-$${AUTH_ALLOWED_SERVICEACCOUNT}}" && \
	  AUTH_ALLOWLIST_ARGS="" && \
	  if [ -n "$$AUTH_ALLOWLIST" ]; then \
	    IFS=',' read -r -a AUTH_ALLOWLIST_ITEMS <<< "$$AUTH_ALLOWLIST"; \
	    for idx in "$${!AUTH_ALLOWLIST_ITEMS[@]}"; do \
	      account="$${AUTH_ALLOWLIST_ITEMS[$$idx]}"; \
	      account="$$(echo -n "$$account" | tr -d '[:space:]')"; \
	      [ -n "$$account" ] || continue; \
	      AUTH_ALLOWLIST_ARGS="$$AUTH_ALLOWLIST_ARGS --set-string auth.allowedServiceAccounts[$$idx]=$$account"; \
	    done; \
	  fi && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  LAST_SEG="$${CONTAINER_IMAGE##*/}" && if [[ "$$LAST_SEG" == *:* ]]; then IMAGE_REPO="$${CONTAINER_IMAGE%:*}"; IMAGE_TAG="$${LAST_SEG##*:}"; else IMAGE_REPO="$${CONTAINER_IMAGE}"; IMAGE_TAG="latest"; fi && \
	  trap 'rm -f .helm-secrets.yaml' EXIT && \
	  umask 077 && \
	  { printf 'secrets:\n  apiKey: "%s"\n' "$${API_KEY}"; \
	    [ -z "$${MLFLOW_TRACKING_TOKEN}" ] || printf '  mlflowTrackingToken: "%s"\n' "$${MLFLOW_TRACKING_TOKEN}"; \
	  } > .helm-secrets.yaml && \
	  helm upgrade --install $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    -f .helm-secrets.yaml \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" \
	    $${AUTH_ENABLED:+--set "auth.enabled=$${AUTH_ENABLED}"} \
	    $${AUTH_ENABLED:+--set "serviceAccount.create=$${AUTH_ENABLED}"} \
	    $${AUTH_AUDIENCE:+--set-string "auth.audience=$${AUTH_AUDIENCE}"} \
	    $${AUTH_ALLOWLIST_ARGS} \
	    $${MLFLOW_TRACKING_URI:+--set env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	    $${MLFLOW_EXPERIMENT_NAME:+--set env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	    $${MLFLOW_TRACKING_AUTH:+--set env.MLFLOW_TRACKING_AUTH="$${MLFLOW_TRACKING_AUTH}"} \
	    $${MLFLOW_TRACKING_INSECURE_TLS:+--set env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
	    $${MLFLOW_TRACKING_SERVER_CERT_PATH:+--set env.MLFLOW_TRACKING_SERVER_CERT_PATH="$${MLFLOW_TRACKING_SERVER_CERT_PATH}"} \
	    $${MLFLOW_WORKSPACE:+--set env.MLFLOW_WORKSPACE="$${MLFLOW_WORKSPACE}"} && \
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
	  AUTH_ALLOWLIST="$${AUTH_ALLOWED_SERVICEACCOUNTS:-$${AUTH_ALLOWED_SERVICEACCOUNT}}" && \
	  AUTH_ALLOWLIST_ARGS="" && \
	  if [ -n "$$AUTH_ALLOWLIST" ]; then \
	    IFS=',' read -r -a AUTH_ALLOWLIST_ITEMS <<< "$$AUTH_ALLOWLIST"; \
	    for idx in "$${!AUTH_ALLOWLIST_ITEMS[@]}"; do \
	      account="$${AUTH_ALLOWLIST_ITEMS[$$idx]}"; \
	      account="$$(echo -n "$$account" | tr -d '[:space:]')"; \
	      [ -n "$$account" ] || continue; \
	      AUTH_ALLOWLIST_ARGS="$$AUTH_ALLOWLIST_ARGS --set-string auth.allowedServiceAccounts[$$idx]=$$account"; \
	    done; \
	  fi && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  LAST_SEG="$${CONTAINER_IMAGE##*/}" && if [[ "$$LAST_SEG" == *:* ]]; then IMAGE_REPO="$${CONTAINER_IMAGE%:*}"; IMAGE_TAG="$${LAST_SEG##*:}"; else IMAGE_REPO="$${CONTAINER_IMAGE}"; IMAGE_TAG="latest"; fi && \
	  helm template $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    --set secrets.apiKey="REDACTED" \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" \
	    $${AUTH_ENABLED:+--set "auth.enabled=$${AUTH_ENABLED}"} \
	    $${AUTH_ENABLED:+--set "serviceAccount.create=$${AUTH_ENABLED}"} \
	    $${AUTH_AUDIENCE:+--set-string "auth.audience=$${AUTH_AUDIENCE}"} \
	    $${AUTH_ALLOWLIST_ARGS} \
	    $${MLFLOW_TRACKING_URI:+--set env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	    $${MLFLOW_TRACKING_TOKEN:+--set secrets.mlflowTrackingToken="REDACTED"} \
	    $${MLFLOW_EXPERIMENT_NAME:+--set env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	    $${MLFLOW_TRACKING_AUTH:+--set env.MLFLOW_TRACKING_AUTH="$${MLFLOW_TRACKING_AUTH}"} \
	    $${MLFLOW_TRACKING_INSECURE_TLS:+--set env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
	    $${MLFLOW_TRACKING_SERVER_CERT_PATH:+--set env.MLFLOW_TRACKING_SERVER_CERT_PATH="$${MLFLOW_TRACKING_SERVER_CERT_PATH}"} \
	    $${MLFLOW_WORKSPACE:+--set env.MLFLOW_WORKSPACE="$${MLFLOW_WORKSPACE}"}

undeploy: ## Remove deployment from cluster
	helm uninstall $(AGENT_NAME)

test: ## Run unit tests (excludes guardrails-integration and cluster integration)
	uv run --extra dev --extra guardrails python -m pytest tests/ \
	  --ignore=tests/integration \
	  -m "not guardrails_integration" $(PYTEST_ARGS)

test-guardrails-integration: ## Run guardrails behavior tests (requires guardrails server + LLM)
	GUARDRAILS_PROFILE=$${GUARDRAILS_PROFILE:-local} \
	  uv run --extra dev --extra guardrails python -m pytest tests/test_guardrails.py \
	  -m guardrails_integration -v --tb=short $(PYTEST_ARGS)

test-guardrails-integration-nemoguard: ## Run guardrails tests against nemoguard profile server
	GUARDRAILS_PROFILE=nemoguard $(MAKE) test-guardrails-integration

test-integration: ## Run cluster deployment integration test
	PYTHONPATH=$$(git rev-parse --show-toplevel)/tests \
	  uv run --extra dev python -m pytest tests/integration/ \
	  -m integration -v --tb=long $(PYTEST_ARGS)
