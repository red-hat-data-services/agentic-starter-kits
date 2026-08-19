SHELL          := bash
AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
REPO_ROOT      := $(shell git rev-parse --show-toplevel 2>/dev/null || echo ../../../..)
CHART_DIR      := ../../deployment
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
MODEL          ?= llama3.1:8b
GUARDRAILS_CR_NAME     := langgraph-guardrailed-agent-guardrails
GUARDRAILS_NAMESPACE   ?= $(shell oc project -q 2>/dev/null)
CLUSTER_ENV            := deploy/overlays/ci-testing/cluster.env
CLUSTER_ENV_EXAMPLE    := deploy/overlays/ci-testing/cluster.env.example
TRACING_COMPOSE        := guardrails/tracing/compose.yaml

.PHONY: init re-init env ollama run-app run-app-fresh build push build-openshift deploy undeploy test test-guardrails-integration test-guardrails-integration-nemoguard test-integration dry-run help guardrails-server-local guardrails-server-nemoguard guardrails-tracing-up guardrails-tracing-down render-guardrails-configmap deploy-guardrails-secrets deploy-guardrails undeploy-guardrails deploy-rhoai undeploy-rhoai deploy-rhoai-dry-run _check-guardrails-ns

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-32s %s\n", $$1, $$2}'

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
	  if [ "$${GUARDRAILS_TRACING_ENABLED:-}" = "true" ]; then \
	    echo "OpenTelemetry tracing ENABLED -> $${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" && \
	    OTEL_SERVICE_NAME="$${OTEL_SERVICE_NAME:-nemo-guardrails}" \
	    OTEL_TRACES_EXPORTER="$${OTEL_TRACES_EXPORTER:-otlp}" \
	    OTEL_METRICS_EXPORTER="$${OTEL_METRICS_EXPORTER:-none}" \
	    OTEL_LOGS_EXPORTER="$${OTEL_LOGS_EXPORTER:-none}" \
	    OTEL_EXPORTER_OTLP_PROTOCOL="$${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
	    OTEL_EXPORTER_OTLP_ENDPOINT="$${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" \
	    opentelemetry-instrument nemoguardrails server --config guardrails/config --default-config-id local --port $${GUARDRAILS_PORT:-8090} --disable-chat-ui; \
	  else \
	    nemoguardrails server --config guardrails/config --default-config-id local --port $${GUARDRAILS_PORT:-8090} --disable-chat-ui; \
	  fi

guardrails-server-nemoguard: ## Generate layered NemoGuard-models config and start NeMo Guardrails proxy
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  cp guardrails/config/nemoguard/config.yaml.example guardrails/config/nemoguard/config.yaml && \
	  python3 guardrails/generate_config.py --profile nemoguard && \
	  echo "Starting NeMo Guardrails server (nemoguard profile) on port $${GUARDRAILS_PORT:-8090}..." && \
	  if [ "$${GUARDRAILS_TRACING_ENABLED:-}" = "true" ]; then \
	    echo "OpenTelemetry tracing ENABLED -> $${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" && \
	    OTEL_SERVICE_NAME="$${OTEL_SERVICE_NAME:-nemo-guardrails}" \
	    OTEL_TRACES_EXPORTER="$${OTEL_TRACES_EXPORTER:-otlp}" \
	    OTEL_METRICS_EXPORTER="$${OTEL_METRICS_EXPORTER:-none}" \
	    OTEL_LOGS_EXPORTER="$${OTEL_LOGS_EXPORTER:-none}" \
	    OTEL_EXPORTER_OTLP_PROTOCOL="$${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
	    OTEL_EXPORTER_OTLP_ENDPOINT="$${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" \
	    opentelemetry-instrument nemoguardrails server --config guardrails/config --default-config-id nemoguard --port $${GUARDRAILS_PORT:-8090} --disable-chat-ui; \
	  else \
	    nemoguardrails server --config guardrails/config --default-config-id nemoguard --port $${GUARDRAILS_PORT:-8090} --disable-chat-ui; \
	  fi

guardrails-tracing-up: ## Start local OTel Collector + Jaeger + Prometheus (needs podman-compose or docker compose)
	@if command -v podman-compose >/dev/null 2>&1; then COMPOSE="podman-compose"; \
	elif docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; \
	else echo "ERROR: install podman-compose (pip install podman-compose) or Docker's compose plugin"; exit 1; fi; \
	$$COMPOSE -f $(TRACING_COMPOSE) up -d && \
	echo "" && \
	echo "Jaeger UI:     http://localhost:16686" && \
	echo "Prometheus UI: http://localhost:9090" && \
	echo "" && \
	echo "Now run: GUARDRAILS_TRACING_ENABLED=true make guardrails-server-local (or -nemoguard)"

guardrails-tracing-down: ## Stop and remove the local tracing stack
	@if command -v podman-compose >/dev/null 2>&1; then podman-compose -f $(TRACING_COMPOSE) down; \
	elif docker compose version >/dev/null 2>&1; then docker compose -f $(TRACING_COMPOSE) down; \
	else echo "ERROR: neither podman-compose nor docker compose found"; exit 1; fi

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
	  $(REPO_ROOT)/scripts/openshift-build-config.sh patch-history $(AGENT_NAME) && \
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
	@helm_status=0; cleanup_status=0; cleanup_script="$(REPO_ROOT)/scripts/openshift-build-config.sh"; \
	helm_output=$$(helm uninstall $(AGENT_NAME) 2>&1); helm_status=$$?; \
	if [ -n "$$helm_output" ]; then \
	  if [ $$helm_status -eq 0 ]; then printf '%s\n' "$$helm_output"; else printf '%s\n' "$$helm_output" >&2; fi; \
	fi; \
	if [ $$helm_status -ne 0 ]; then \
	  case "$$helm_output" in *"Release not loaded"*|*"release: not found"*) helm_status=0 ;; esac; \
	fi; \
	if [ -f "$$cleanup_script" ]; then \
	  bash "$$cleanup_script" cleanup $(AGENT_NAME) || cleanup_status=$$?; \
	else \
	  echo "WARNING: cleanup script not found: $$cleanup_script" >&2; \
	fi; \
	if [ $$helm_status -ne 0 ]; then exit $$helm_status; fi; \
	exit $$cleanup_status

render-guardrails-configmap: ## Render NeMo Guardrails ConfigMap manifest for cluster deploy
	@CLUSTER_ENV_FILE="$(CLUSTER_ENV)"; \
	  [ -f "$$CLUSTER_ENV_FILE" ] || CLUSTER_ENV_FILE="$(CLUSTER_ENV_EXAMPLE)"; \
	  python3 deploy/scripts/render_guardrails_configmap.py \
	    --cluster-env "$$CLUSTER_ENV_FILE" \
	    --output deploy/manifests/02-guardrails-configmap.yaml

_check-guardrails-ns:
	@[ -n "$(GUARDRAILS_NAMESPACE)" ] || { echo "ERROR: GUARDRAILS_NAMESPACE is empty. Log in with oc or pass GUARDRAILS_NAMESPACE=<ns>."; exit 1; }

deploy-guardrails-secrets: _check-guardrails-ns ## Create/update guardrails Secret from cluster.env or NVIDIA_API_KEY env
	@KEY=""; \
	  if [ -n "$${NVIDIA_API_KEY:-}" ]; then KEY="$${NVIDIA_API_KEY}"; \
	  elif [ -f "$(CLUSTER_ENV)" ]; then \
	    set -a && source "$(CLUSTER_ENV)" && set +a; KEY="$${NVIDIA_API_KEY}"; \
	  fi; \
	  [ -n "$$KEY" ] && [ "$$KEY" != "replace-me" ] || { \
	    echo "ERROR: Set NVIDIA_API_KEY in env or $(CLUSTER_ENV)"; exit 1; \
	  }; \
	  API_KEY_VAL="$${API_KEY:-not-needed}"; \
	  if [ -f "$(CLUSTER_ENV)" ]; then \
	    set -a && source "$(CLUSTER_ENV)" && set +a; \
	    API_KEY_VAL="$${API_KEY:-not-needed}"; \
	  fi; \
	  oc create secret generic langgraph-guardrailed-agent-guardrails-secrets \
	    --namespace="$(GUARDRAILS_NAMESPACE)" \
	    --from-literal=api-key="$$API_KEY_VAL" \
	    --from-literal=nvidia-api-key="$$KEY" \
	    --dry-run=client -o yaml | oc apply -f -

deploy-guardrails: _check-guardrails-ns render-guardrails-configmap deploy-guardrails-secrets ## Apply NemoGuardrails CR + ConfigMap to GUARDRAILS_NAMESPACE
	@command -v envsubst >/dev/null 2>&1 || { echo "ERROR: envsubst (gettext) is required"; exit 1; }
	@set -a && [ -f "$(CLUSTER_ENV)" ] && source "$(CLUSTER_ENV)" || source "$(CLUSTER_ENV_EXAMPLE)"; set +a && \
	  CR_TMP=$$(mktemp) && \
	  trap 'rm -f "$$CR_TMP"' EXIT && \
	  OTEL_SERVICE_NAME="$${OTEL_SERVICE_NAME:-nemo-guardrails}" \
	  OTEL_EXPORTER_OTLP_PROTOCOL="$${OTEL_EXPORTER_OTLP_PROTOCOL:-grpc}" \
	  OTEL_METRICS_EXPORTER="$${OTEL_METRICS_EXPORTER:-none}" \
	  envsubst '$$OTEL_EXPORTER_OTLP_ENDPOINT $$OTEL_SERVICE_NAME $$OTEL_EXPORTER_OTLP_PROTOCOL $$OTEL_METRICS_EXPORTER' \
	    < deploy/manifests/03-nemoguardrails-cr.yaml > "$$CR_TMP" && \
	  python3 deploy/scripts/finalize_nemoguardrails_cr.py "$$CR_TMP" && \
	  oc apply -n "$(GUARDRAILS_NAMESPACE)" -f "$$CR_TMP" && \
	  oc apply -n "$(GUARDRAILS_NAMESPACE)" -f deploy/manifests/02-guardrails-configmap.yaml && \
	  echo "" && echo "Waiting for NemoGuardrails pod in $(GUARDRAILS_NAMESPACE)..." && \
	  for i in $$(seq 1 60); do \
	    READY=$$(oc get pods -n "$(GUARDRAILS_NAMESPACE)" \
	      -l app.kubernetes.io/instance=$(GUARDRAILS_CR_NAME) \
	      -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true); \
	    if [ "$$READY" = "True" ]; then \
	      echo "Guardrails pod ready."; \
	      break; \
	    fi; \
	    if [ $$i -eq 60 ]; then \
	      echo "WARNING: Guardrails pod not ready after 5 minutes. Check:"; \
	      echo "  oc get nemoguardrails,pods -n $(GUARDRAILS_NAMESPACE) | grep guardrails"; \
	      exit 1; \
	    fi; \
	    sleep 5; \
	  done && \
	  echo "" && \
	  echo "In-cluster URL: http://$(GUARDRAILS_CR_NAME).$(GUARDRAILS_NAMESPACE).svc.cluster.local/v1" && \
	  ROUTE=$$(oc get route $(GUARDRAILS_CR_NAME) -n "$(GUARDRAILS_NAMESPACE)" \
	    -o jsonpath='{.spec.host}' 2>/dev/null || true); \
	  if [ -n "$$ROUTE" ]; then \
	    echo "Route URL: https://$$ROUTE"; \
	  fi

undeploy-guardrails: _check-guardrails-ns ## Remove NemoGuardrails CR + ConfigMap + Secret from GUARDRAILS_NAMESPACE
	@oc delete nemoguardrails $(GUARDRAILS_CR_NAME) \
	    -n "$(GUARDRAILS_NAMESPACE)" --ignore-not-found && \
	  oc delete configmap langgraph-guardrailed-agent-guardrails-config \
	    -n "$(GUARDRAILS_NAMESPACE)" --ignore-not-found && \
	  oc delete secret langgraph-guardrailed-agent-guardrails-secrets \
	    -n "$(GUARDRAILS_NAMESPACE)" --ignore-not-found

deploy-rhoai-dry-run: _check-guardrails-ns render-guardrails-configmap ## Preview namespaced CR + ConfigMap (no apply)
	@command -v envsubst >/dev/null 2>&1 || { echo "ERROR: envsubst (gettext) is required"; exit 1; }
	@set -a && [ -f "$(CLUSTER_ENV)" ] && source "$(CLUSTER_ENV)" || source "$(CLUSTER_ENV_EXAMPLE)"; set +a && \
	  CR_TMP=$$(mktemp) && \
	  trap 'rm -f "$$CR_TMP"' EXIT && \
	  OTEL_SERVICE_NAME="$${OTEL_SERVICE_NAME:-nemo-guardrails}" \
	  OTEL_EXPORTER_OTLP_PROTOCOL="$${OTEL_EXPORTER_OTLP_PROTOCOL:-grpc}" \
	  OTEL_METRICS_EXPORTER="$${OTEL_METRICS_EXPORTER:-none}" \
	  envsubst '$$OTEL_EXPORTER_OTLP_ENDPOINT $$OTEL_SERVICE_NAME $$OTEL_EXPORTER_OTLP_PROTOCOL $$OTEL_METRICS_EXPORTER' \
	    < deploy/manifests/03-nemoguardrails-cr.yaml > "$$CR_TMP" && \
	  python3 deploy/scripts/finalize_nemoguardrails_cr.py "$$CR_TMP" && \
	  echo "--- namespace: $(GUARDRAILS_NAMESPACE) ---" && \
	  oc apply -n "$(GUARDRAILS_NAMESPACE)" --dry-run=client -o yaml -f "$$CR_TMP" && \
	  oc apply -n "$(GUARDRAILS_NAMESPACE)" --dry-run=client -o yaml -f deploy/manifests/02-guardrails-configmap.yaml

deploy-rhoai: deploy-guardrails ## Deploy guardrails proxy then agent (BASE_URL must target guardrails)
	@source .env 2>/dev/null || true; \
	  EXPECTED="http://$(GUARDRAILS_CR_NAME).$(GUARDRAILS_NAMESPACE).svc.cluster.local/v1"; \
	  if [ "$${BASE_URL}" != "$$EXPECTED" ]; then \
	    echo "ERROR: BASE_URL=$${BASE_URL:-<unset>} — set it to $$EXPECTED in .env (current oc project)."; \
	    exit 1; \
	  fi
	@$(MAKE) deploy

undeploy-rhoai: undeploy undeploy-guardrails ## Remove agent and guardrails from cluster

test: ## Run unit tests (excludes guardrails-integration, cluster integration, behavioral)
	uv run --extra dev --extra guardrails python -m pytest tests/ \
	  --ignore=tests/integration \
	  --ignore=tests/behavioral \
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
	  -m integration -v --tb=long --junitxml=results.xml $(PYTEST_ARGS)
