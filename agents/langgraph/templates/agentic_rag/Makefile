SHELL          := bash
AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
REPO_ROOT      := $(shell git rev-parse --show-toplevel 2>/dev/null || echo ../../../..)
CHART_DIR      := ../../deployment
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
MODEL          ?= llama3.1:8b
OLLAMA_EMBEDDING_MODEL ?= embeddinggemma:latest

.PHONY: init re-init env ollama ogx-server run-app run-app-fresh run-cli load-docs build push build-openshift deploy undeploy test test-integration eval dry-run refresh-certs setup-gateway teardown-gateway build-openshell create-sandbox wait-sandbox setup-egress load-docs-sandbox check-collection start-agent deploy-openshell undeploy-openshell playground-sandbox expose-agent help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

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
	  echo "  make ollama        # install Ollama and pull models" && \
	  echo "  make ogx-server    # start OGX server"

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
	  echo "==> Pulling embedding model ($(OLLAMA_EMBEDDING_MODEL))..." && \
	  ollama pull $(OLLAMA_EMBEDDING_MODEL) && \
	  echo "" && \
	  echo "Done. Run 'make ogx-server' to start the OGX server."

ogx-server: ## Install OGX and start OGX server
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "==> Installing OGX..." && \
	  uv pip install "ogx[starter]==1.1.0" "ogx-api==1.1.0" ollama "pymilvus==2.6.9" "milvus-lite>=2.5.1" "setuptools>=80.9.0,<82.0.0" && \
	  mkdir -p ../../../../milvus_data && \
	  echo "==> Killing any existing process on port 8321..." && \
	  lsof -ti:8321 | xargs kill -9 2>/dev/null; true && \
	  echo "==> Starting OGX server on port 8321..." && \
	  ogx run ../../../../run_ogx_server.yaml

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

run-cli: ## Run interactive CLI chat (no web server)
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  cd examples && uv run $${MLFLOW_TRACKING_URI:+--extra tracing} python execute_ai_service_locally.py

load-docs: ## Load documents into vector store
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  uv run python data/load_documents.py

build: ## Build container image locally (podman/docker)
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; } && \
	  source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  rm -rf ./images ./components/auth && \
	  trap 'rm -rf ./images ./components/auth; rmdir ./components 2>/dev/null || true' EXIT && \
	  cp -r ../../../../images ./images && \
	  mkdir -p ./components && cp -r ../../../../components/auth ./components/auth && \
	  $(CONTAINER_CLI) build --platform linux/amd64 -t "$${CONTAINER_IMAGE}" -f Dockerfile .

push: ## Push container image to registry
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; } && \
	  source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  $(CONTAINER_CLI) push "$${CONTAINER_IMAGE}"

build-openshift: ## Build image in-cluster via OpenShift BuildConfig (no podman/docker needed)
	@rm -rf ./images ./components/auth && \
	  trap 'rm -rf ./images ./components/auth; rmdir ./components 2>/dev/null || true' EXIT && \
	  cp -r ../../../../images ./images && \
	  mkdir -p ./components && cp -r ../../../../components/auth ./components/auth && \
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
	    $${AUTH_ENABLED:+--set "auth.createAuthDelegatorBinding=$${AUTH_ENABLED}"} \
	    $${AUTH_AUDIENCE:+--set-string "auth.audience=$${AUTH_AUDIENCE}"} \
	    $${AUTH_ALLOWLIST_ARGS} \
	    $${EMBEDDING_MODEL:+--set env.EMBEDDING_MODEL="$${EMBEDDING_MODEL}"} \
	    $${EMBEDDING_DIMENSION:+--set env.EMBEDDING_DIMENSION="$${EMBEDDING_DIMENSION}"} \
	    $${VECTOR_STORE_ID:+--set env.VECTOR_STORE_ID="$${VECTOR_STORE_ID}"} \
	    $${VECTOR_STORE_PROVIDER:+--set env.VECTOR_STORE_PROVIDER="$${VECTOR_STORE_PROVIDER}"} \
	    $${MLFLOW_TRACKING_URI:+--set env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	    $${MLFLOW_EXPERIMENT_NAME:+--set env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	    $${MLFLOW_TRACKING_INSECURE_TLS:+--set env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
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
	    $${AUTH_ENABLED:+--set "auth.createAuthDelegatorBinding=$${AUTH_ENABLED}"} \
	    $${AUTH_AUDIENCE:+--set-string "auth.audience=$${AUTH_AUDIENCE}"} \
	    $${AUTH_ALLOWLIST_ARGS} \
	    $${EMBEDDING_MODEL:+--set env.EMBEDDING_MODEL="$${EMBEDDING_MODEL}"} \
	    $${EMBEDDING_DIMENSION:+--set env.EMBEDDING_DIMENSION="$${EMBEDDING_DIMENSION}"} \
	    $${VECTOR_STORE_ID:+--set env.VECTOR_STORE_ID="$${VECTOR_STORE_ID}"} \
	    $${VECTOR_STORE_PROVIDER:+--set env.VECTOR_STORE_PROVIDER="$${VECTOR_STORE_PROVIDER}"} \
	    $${MLFLOW_TRACKING_URI:+--set env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	    $${MLFLOW_TRACKING_TOKEN:+--set secrets.mlflowTrackingToken="REDACTED"} \
	    $${MLFLOW_EXPERIMENT_NAME:+--set env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	    $${MLFLOW_TRACKING_INSECURE_TLS:+--set env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
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

## ── openShell sandbox targets ─────────────────────────────────────────────────
OPENSHELL_SANDBOX ?= $(shell . ./.env 2>/dev/null && echo $${OPENSHELL_SANDBOX_NAME:-rag-sandbox})
OPENSHELL_IMAGE   := openshell-agentic-rag
OPENSHELL_VERSION ?= 0.0.99

refresh-certs: ## Refresh openShell client certificates from cluster
	@echo "==> Refreshing openShell client certificates..." && \
	  MTLS_DIR=~/.config/openshell/gateways/openshift/mtls && mkdir -p $$MTLS_DIR && \
	  oc -n openshell get secret openshell-client-tls -o jsonpath='{.data.ca\.crt}'  | base64 -d > $$MTLS_DIR/ca.crt && \
	  oc -n openshell get secret openshell-client-tls -o jsonpath='{.data.tls\.crt}' | base64 -d > $$MTLS_DIR/tls.crt && \
	  oc -n openshell get secret openshell-client-tls -o jsonpath='{.data.tls\.key}' | base64 -d > $$MTLS_DIR/tls.key && \
	  echo "    Certificates refreshed."

setup-gateway: ## Install openShell gateway, create Route, register CLI (one-time)
	@set -e && \
	  APPS_DOMAIN=$$(oc get ingresses.config cluster -o jsonpath='{.spec.domain}') && \
	  echo "==> Detected apps domain: $$APPS_DOMAIN" && \
	  echo "==> Ensuring openshell namespace and SCCs..." && \
	  oc create ns openshell 2>/dev/null || true && \
	  oc adm policy add-scc-to-user privileged -z openshell-sandbox -n openshell 2>/dev/null || true && \
	  oc adm policy add-scc-to-user privileged -z openshell -n openshell 2>/dev/null || true && \
	  echo "==> Granting TokenReview RBAC to sandbox SA..." && \
	  oc create clusterrolebinding openshell-tokenreview \
	    --clusterrole=system:auth-delegator \
	    --serviceaccount=openshell:openshell-sandbox 2>/dev/null || true && \
	  echo "==> Installing openShell gateway $(OPENSHELL_VERSION)..." && \
	  helm upgrade --install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
	    --version $(OPENSHELL_VERSION) \
	    --namespace openshell \
	    --set securityContext.runAsUser=null \
	    --set securityContext.runAsNonRoot=false \
	    --set securityContext.allowPrivilegeEscalation=true \
	    --set securityContext.capabilities=null \
	    --set server.auth.allowUnauthenticatedUsers=true \
	    --set "pkiInitJob.serverDnsNames={*.openshell.$$APPS_DOMAIN,openshell.$$APPS_DOMAIN,openshell-gateway-openshell.$$APPS_DOMAIN}" && \
	  echo "==> Waiting for gateway to be ready..." && \
	  oc -n openshell rollout status statefulset/openshell --timeout=120s && \
	  echo "==> Disabling mTLS client cert requirement..." && \
	  TOML=$$(oc -n openshell get configmap openshell-config -o jsonpath='{.data.gateway\.toml}' | sed '/^client_ca_path/d') && \
	  oc -n openshell patch configmap openshell-config --type merge \
	    -p "$$(printf '{"data":{"gateway.toml":%s}}' "$$(printf '%s' "$$TOML" | jq -Rs .)")" && \
	  oc -n openshell delete pod openshell-0 && \
	  oc -n openshell rollout status statefulset/openshell --timeout=120s && \
	  echo "==> Creating gateway Route..." && \
	  oc -n openshell create route passthrough openshell-gateway \
	    --service=openshell --port=8080 2>/dev/null || true && \
	  GATEWAY_URL="https://openshell-gateway-openshell.$$APPS_DOMAIN" && \
	  echo "==> Registering gateway in CLI..." && \
	  openshell gateway remove openshift 2>/dev/null || true && \
	  MTLS_DIR=~/.config/openshell/gateways/openshift/mtls && mkdir -p $$MTLS_DIR && \
	  oc -n openshell get secret openshell-client-tls -o jsonpath='{.data.ca\.crt}'  | base64 -d > $$MTLS_DIR/ca.crt && \
	  oc -n openshell get secret openshell-client-tls -o jsonpath='{.data.tls\.crt}' | base64 -d > $$MTLS_DIR/tls.crt && \
	  oc -n openshell get secret openshell-client-tls -o jsonpath='{.data.tls\.key}' | base64 -d > $$MTLS_DIR/tls.key && \
	  openshell gateway add "$$GATEWAY_URL" --local --name openshift && \
	  echo "==> Verifying connection..." && \
	  export OPENSHELL_GATEWAY_INSECURE=true && \
	  openshell status && \
	  echo "" && \
	  echo "Gateway ready. Next: make build-openshell"

teardown-gateway: ## Uninstall openShell gateway and clean up
	@openshell gateway remove openshift 2>/dev/null || true && \
	  helm uninstall openshell -n openshell 2>/dev/null || true && \
	  oc -n openshell delete pvc --all 2>/dev/null || true && \
	  oc -n openshell delete secret openshell-server-tls openshell-client-tls openshell-jwt-keys 2>/dev/null || true && \
	  oc -n openshell delete route --all 2>/dev/null || true && \
	  oc delete clusterrolebinding openshell-tokenreview 2>/dev/null || true && \
	  oc adm policy remove-scc-from-user privileged -z openshell-sandbox -n openshell 2>/dev/null || true && \
	  oc adm policy remove-scc-from-user privileged -z openshell -n openshell 2>/dev/null || true && \
	  echo "Gateway removed."

build-openshell: ## Build openShell sandbox image via OpenShift BuildConfig
	@rm -rf ./images ./components && \
	  trap 'rm -rf ./images ./components' EXIT && \
	  cp -r ../../../../images ./images && \
	  mkdir -p ./components && cp -r ../../../../components/auth ./components/auth && \
	  oc new-build --strategy=docker --binary \
	    --name=$(OPENSHELL_IMAGE) --to=$(OPENSHELL_IMAGE):latest 2>/dev/null || true && \
	  oc patch bc $(OPENSHELL_IMAGE) \
	    -p '{"spec":{"strategy":{"dockerStrategy":{"dockerfilePath":"Containerfile.openshell"}}}}' && \
	  oc start-build $(OPENSHELL_IMAGE) --from-dir=. --follow && \
	  NS=$$(oc project -q) && \
	  echo "" && \
	  echo "Image ready: image-registry.openshift-image-registry.svc:5000/$$NS/$(OPENSHELL_IMAGE):latest" && \
	  echo "Next: make deploy-openshell"

_openshell-env = . ./.env && export OPENSHELL_GATEWAY_INSECURE=true && \
	SANDBOX=$${OPENSHELL_SANDBOX_NAME:-rag-sandbox} && \
	NS=$$(oc project -q) && \
	IMAGE="image-registry.openshift-image-registry.svc:5000/$$NS/$(OPENSHELL_IMAGE):latest" && \
	APPS_DOMAIN=$$(oc get ingresses.config cluster -o jsonpath='{.spec.domain}')

create-sandbox: ## Delete existing sandbox and create a new one (with 120s timeout)
	@$(_openshell-env) && \
	  echo "==> Granting image-pull to openshell namespace..." && \
	  oc policy add-role-to-user system:image-puller "system:serviceaccount:openshell:openshell-sandbox" -n "$$NS" 2>/dev/null || true
	@$(_openshell-env) && \
	  oc policy add-role-to-user system:image-puller "system:serviceaccount:openshell:default" -n "$$NS" 2>/dev/null || true
	@$(_openshell-env) && \
	  echo "==> Deleting old sandbox $$SANDBOX..." && \
	  openshell sandbox delete "$$SANDBOX" 2>/dev/null || true
	@$(_openshell-env) && \
	  echo "==> Creating sandbox $$SANDBOX from $$IMAGE..." && \
	  echo "    (timeout 120s — this may take a minute while the image is pulled)..." && \
	  openshell sandbox create --name "$$SANDBOX" --from "$$IMAGE" \
	    --env "BASE_URL=$$BASE_URL" \
	    --env "MODEL_ID=$$MODEL_ID" \
	    --env "API_KEY=$$API_KEY" \
	    --env "MAAS_API_KEY=$$MAAS_API_KEY" \
	    --env "MAAS_BASE_URL=$$MAAS_BASE_URL" \
	    --env "EMBEDDING_MODEL=$$EMBEDDING_MODEL" \
	    --env "EMBEDDING_DIMENSION=$${EMBEDDING_DIMENSION:-1024}" \
	    --env "MILVUS_URI=$$MILVUS_URI" \
	    --env "MILVUS_TOKEN=$$MILVUS_TOKEN" \
	    --env "PORT=8080" </dev/null & \
	  CPID=$$!; ( sleep 80 && kill $$CPID 2>/dev/null ) & TPID=$$!; \
	  wait $$CPID 2>/dev/null; RC=$$?; kill $$TPID 2>/dev/null; wait $$TPID 2>/dev/null; \
	  if [ $$RC -ne 0 ]; then echo "    sandbox create exited with $$RC (may still be starting — wait-sandbox will poll)"; fi; true

wait-sandbox: ## Poll until sandbox phase is Ready (max 150s)
	@$(_openshell-env) && \
	  echo "==> Waiting for sandbox $$SANDBOX to be ready..." && \
	  i=0; while [ $$i -lt 30 ]; do \
	    i=$$((i+1)); \
	    phase=$$(openshell sandbox list 2>/dev/null | grep "$$SANDBOX" | awk '{print $$NF}' | sed 's/\x1b\[[0-9;]*m//g'); \
	    if [ "$$phase" = "Ready" ]; then echo "    Sandbox ready."; exit 0; fi; \
	    echo "    status: $$phase (attempt $$i/30, waiting 5s...)"; \
	    sleep 5; \
	  done; \
	  echo "ERROR: sandbox not ready after 150s"; exit 1

setup-egress: ## Add MaaS + Milvus egress policies for agent Python binary
	@$(_openshell-env) && \
	  echo "==> Using agent Python binary: /usr/bin/python3.12" && \
	  PYTHON_BIN="/usr/bin/python3.12" && \
	  echo "==> Adding egress policy for MaaS (chat model)..." && \
	  MAAS_CHAT_HOST=$$(echo "$$BASE_URL" | sed -E 's|^https?://||;s|/.*||') && \
	  openshell policy update "$$SANDBOX" --add-endpoint "$$MAAS_CHAT_HOST:443" --binary "$$PYTHON_BIN" --wait && \
	  echo "==> Adding egress policy for MaaS (embeddings)..." && \
	  MAAS_EMB_HOST=$$(echo "$$MAAS_BASE_URL" | sed -E 's|^https?://||;s|/.*||') && \
	  openshell policy update "$$SANDBOX" --add-endpoint "$$MAAS_EMB_HOST:443" --binary "$$PYTHON_BIN" --wait && \
	  echo "==> Adding egress policies for K8s API + Milvus (tls: skip — bypass proxy TLS inspection)..." && \
	  MILVUS_HOSTPORT=$$(echo "$$MILVUS_URI" | sed -E 's|^https?://||;s|/.*||') && \
	  MILVUS_HOST_ONLY=$$(echo "$$MILVUS_HOSTPORT" | cut -d: -f1) && \
	  MILVUS_PORT_ONLY=$$(echo "$$MILVUS_HOSTPORT" | cut -d: -f2) && \
	  POLICY_FILE=$$(mktemp /tmp/openshell-policy.XXXXXX) && \
	  export MILVUS_H="$$MILVUS_HOST_ONLY" MILVUS_P="$$MILVUS_PORT_ONLY" PY_BIN="$$PYTHON_BIN" && \
	  openshell policy get "$$SANDBOX" --full -o json 2>/dev/null | sed -n '/^{/,$$p' | \
	    python3 -c 'import json,sys,os;d=json.load(sys.stdin);p=d["policy"];p["network_policies"]["k8s_api"]={"name":"k8s-api","endpoints":[{"host":"kubernetes.default.svc","port":443,"tls":"skip"}],"binaries":[{"path":os.environ["PY_BIN"]}]};p["network_policies"]["milvus_grpc"]={"name":"milvus-grpc","endpoints":[{"host":os.environ["MILVUS_H"],"port":int(os.environ["MILVUS_P"]),"tls":"skip"}],"binaries":[{"path":os.environ["PY_BIN"]}]};json.dump(p,sys.stdout,indent=2)' > "$$POLICY_FILE" && \
	  openshell policy set "$$SANDBOX" --policy "$$POLICY_FILE" --wait && \
	  rm -f "$$POLICY_FILE" && \
	  echo "Done!"

load-docs-sandbox: ## Load documents into Milvus using OpenShift Job with ai4rag, update MILVUS_COLLECTION_NAME in .env
	@./scripts/create-load-docs-job-ai4rag.sh

check-collection: ## Check if Milvus collection exists and show details
	@$(_openshell-env) && \
	  if [ -z "$$MILVUS_COLLECTION_NAME" ]; then echo "ERROR: MILVUS_COLLECTION_NAME not set in .env"; exit 1; fi && \
	  echo "==> Copying check_collection.py to sandbox..." && \
	  oc exec -n openshell "default--$$SANDBOX" -- mkdir -p /sandbox/scripts && \
	  oc cp scripts/check_collection.py openshell/"default--$$SANDBOX":/sandbox/scripts/check_collection.py 2>/dev/null && \
	  echo "==> Checking Milvus collection: $$MILVUS_COLLECTION_NAME" && \
	  oc exec -n openshell "default--$$SANDBOX" -- bash -c '\
	    export MILVUS_URI="'"$$MILVUS_URI"'" && \
	    export MILVUS_TOKEN="'"$$MILVUS_TOKEN"'" && \
	    export MILVUS_SERVER_CERT="/sandbox/data/certs/milvus-ca.crt" && \
	    export MILVUS_COLLECTION_NAME="'"$$MILVUS_COLLECTION_NAME"'" && \
	    export PYTHONPATH=/sandbox/.local/lib/python3.12/site-packages:/sandbox/.local/lib64/python3.12/site-packages:/sandbox && \
	    cd /sandbox && /usr/bin/python3.12 scripts/check_collection.py' 2>&1 | grep -v "PyMilvusDeprecationWarning"

start-agent: refresh-certs ## Start agent with external URL access and K8s ServiceAccount auth
	@$(_openshell-env) && \
	  if [ -z "$$MILVUS_COLLECTION_NAME" ]; then echo "ERROR: MILVUS_COLLECTION_NAME not set in .env. Run 'make load-docs-sandbox' first."; exit 1; fi && \
	  echo "==> Creating agent-client ServiceAccount and token..." && \
	  oc create sa agent-client 2>/dev/null || true && \
	  CLIENT_TOKEN=$$(oc create token agent-client --duration=168h) && \
	  oc delete secret agent-client-token 2>/dev/null || true && \
	  oc create secret generic agent-client-token --from-literal=token="$$CLIENT_TOKEN" && \
	  echo "==> Generating sandbox reviewer token..." && \
	  K8S_API_URL="https://kubernetes.default.svc" && \
	  K8S_REVIEWER_TOKEN=$$(oc create token openshell-sandbox -n openshell --duration=168h) && \
	  ALLOWED_SA_USERNAME="system:serviceaccount:$${NS}:agent-client" && \
	  echo "==> Stopping any running agent..." && \
	  oc exec -n openshell "default--$$SANDBOX" -- bash -c "pkill -f python3" 2>/dev/null || true && \
	  sleep 5 && \
	  echo "==> Starting agent (collection: $$MILVUS_COLLECTION_NAME, auth: enabled)..." && \
	  openshell sandbox exec -n "$$SANDBOX" -- bash -c '\
	    export API_KEY="'"$$API_KEY"'" && \
	    export BASE_URL="'"$$BASE_URL"'" && \
	    export MODEL_ID="'"$$MODEL_ID"'" && \
	    export MAAS_API_KEY="'"$$MAAS_API_KEY"'" && \
	    export MAAS_BASE_URL="'"$$MAAS_BASE_URL"'" && \
	    export EMBEDDING_MODEL="'"$$EMBEDDING_MODEL"'" && \
	    export EMBEDDING_DIMENSION="'"$$EMBEDDING_DIMENSION"'" && \
	    export MILVUS_URI="'"$$MILVUS_URI"'" && \
	    export MILVUS_TOKEN="'"$$MILVUS_TOKEN"'" && \
	    export MILVUS_COLLECTION_NAME="'"$$MILVUS_COLLECTION_NAME"'" && \
	    export MILVUS_SERVER_CERT="/sandbox/data/certs/milvus-ca.crt" && \
	    export MILVUS_SERVER_NAME="'"$$MILVUS_SERVER_NAME"'" && \
	    export K8S_API_URL="'"$$K8S_API_URL"'" && \
	    export K8S_REVIEWER_TOKEN="'"$$K8S_REVIEWER_TOKEN"'" && \
	    export ALLOWED_SA_USERNAME="'"$$ALLOWED_SA_USERNAME"'" && \
	    export PYTHONPATH=/sandbox/.local/lib/python3.12/site-packages:/sandbox/.local/lib64/python3.12/site-packages:/sandbox && \
	    cd /sandbox && \
	    nohup /usr/bin/python3.12 -m uvicorn auth_wrapper:app --host 0.0.0.0 --port 8080 > /sandbox/agent.log 2>&1 &\
	    echo $$! > /sandbox/agent.pid && \
	    sleep 3 && \
	    if kill -0 $$! 2>/dev/null; then echo "Agent process alive"; else echo "ERROR: Agent died on startup"; cat /sandbox/agent.log; exit 1; fi' && \
	  echo "    Agent started in background."

expose-agent: ## Expose agent service and create Route
	@$(_openshell-env) && \
	  echo "==> Exposing service URL..." && \
	  openshell service expose "$$SANDBOX" 8080 agent 2>/dev/null || true && \
	  sleep 2 && \
	  SVC_HOST="default--$$SANDBOX--agent.openshell.$$APPS_DOMAIN" && \
	  printf 'apiVersion: route.openshift.io/v1\nkind: Route\nmetadata:\n  name: openshell-rag-agent\n  namespace: openshell\nspec:\n  host: "%s"\n  to:\n    kind: Service\n    name: openshell\n  port:\n    targetPort: grpc\n  tls:\n    termination: passthrough\n' "$$SVC_HOST" | oc apply -f - && \
	  echo "==> Waiting for agent to initialize (10s)..." && \
	  sleep 10 && \
	  echo "==> Checking agent health..." && \
	  curl -sk -m 3 "https://$$SVC_HOST/health" 2>/dev/null || echo "Agent not ready yet (check logs)" && \
	  echo "" && \
	  echo "════════════════════════════════════════════════════════════════" && \
	  echo "Agent URL: https://$$SVC_HOST" && \
	  echo "" && \
	  echo "Get token:" && \
	  echo "  TOKEN=\$$(oc get secret agent-client-token -o jsonpath='{.data.token}' | base64 -d)" && \
	  echo "" && \
	  echo "Query:" && \
	  echo "  curl -sk https://$$SVC_HOST/chat/completions \\" && \
	  echo "    -H \"X-Api-Key: \$$TOKEN\" \\" && \
	  echo "    -H 'Content-Type: application/json' \\" && \
	  echo "    -d '{\"messages\":[{\"role\":\"user\",\"content\":\"What are appropriate chunk sizes?\"}]}'" && \
	  echo "" && \
	  echo "Check logs:" && \
	  echo "  oc exec -n openshell default--$$SANDBOX -- tail -50 /sandbox/agent.log" && \
	  echo "════════════════════════════════════════════════════════════════"

deploy-openshell: create-sandbox wait-sandbox setup-egress start-agent expose-agent ## Create sandbox, start agent, expose public URL

undeploy-openshell: ## Remove openShell sandbox and route
	@export OPENSHELL_GATEWAY_INSECURE=true && \
	  (openshell sandbox delete $(OPENSHELL_SANDBOX) 2>/dev/null || true) && \
	  oc -n openshell delete route openshell-rag-agent 2>/dev/null || true && \
	  echo "Sandbox $(OPENSHELL_SANDBOX) and route removed." && \
	  sleep 10 2>/dev/null || true

playground-sandbox: ## Start sandbox playground web UI (auto-fetches agent URL and SA token)
	@. .venv/bin/activate && \
	  echo "Starting sandbox playground on http://localhost:5002" && \
	  echo "Auto-fetching agent URL from OpenShift Route..." && \
	  echo "Auto-fetching SA token from Secret agent-client-token..." && \
	  echo "" && \
	  python playground-sandbox/app.py

eval: ## Run MLflow GenAI evaluation
	@uv run --extra eval python evaluation/run_eval.py

test: ## Run unit tests
	uv run --extra dev python -m pytest tests/ --ignore=tests/integration --ignore=tests/behavioral $(PYTEST_ARGS)

test-integration: ## Run integration deployment test
	PYTHONPATH=$$(git rev-parse --show-toplevel)/tests \
	  uv run --extra dev python -m pytest tests/integration/test_deployment.py \
	    -v --tb=long --junitxml=results.xml
