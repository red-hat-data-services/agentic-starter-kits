SHELL          := bash
AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
CHART_DIR      := ../../deployment
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)

.PHONY: init re-init env test run-app run-app-fresh run-crew run-langgraph build push deploy undeploy dry-run help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

re-init: ## Activate venv and reload .env variables
	@source .venv/bin/activate && set -a && source .env && set +a && \
	  echo "Venv activated and .env variables loaded."

init: ## Create .env from template.env if missing
	@if [ ! -f .env ]; then cp template.env .env && echo "Created .env from template.env — edit it with your configuration"; else echo ".env already exists — skipping"; fi

env: ## Create venv and install dependencies (uv sync)
	@echo "==> Creating/syncing virtual environment (Python 3.12)..." && \
	uv sync --python 3.12 && \
	echo "" && \
	echo "Done. Next: configure .env (make init), then make run-app"

test: ## Run tests (pytest)
	uv run --with pytest pytest tests/ --ignore=tests/integration --ignore=tests/behavioral -v $(PYTEST_ARGS)

run-crew: ## Run CrewAI A2A server only (CREW_A2A_PORT, default 9100)
	@[ -d .venv ] || { echo "ERROR: No .venv — run: make env  (or: uv venv --python 3.12 && uv sync)"; exit 1; }
	@source .venv/bin/activate && set -a && source .env && set +a && \
	CREW_PORT=$${CREW_A2A_PORT:-9100}; \
	if command -v lsof >/dev/null 2>&1 && lsof -ti:$$CREW_PORT >/dev/null 2>&1; then \
	  echo "ERROR: Port $$CREW_PORT is already in use. Change CREW_A2A_PORT or run: make run-app-fresh"; \
	  exit 1; \
	fi && \
	uv run $${MLFLOW_TRACKING_URI:+--extra tracing} python -m a2a_langgraph_crewai.crew_a2a_server

run-langgraph: ## Run LangGraph A2A server only (LANGGRAPH_A2A_PORT, default 9200)
	@[ -d .venv ] || { echo "ERROR: No .venv — run: make env  (or: uv venv --python 3.12 && uv sync)"; exit 1; }
	@source .venv/bin/activate && set -a && source .env && set +a && \
	LG_PORT=$${LANGGRAPH_A2A_PORT:-9200}; \
	if command -v lsof >/dev/null 2>&1 && lsof -ti:$$LG_PORT >/dev/null 2>&1; then \
	  echo "ERROR: Port $$LG_PORT is already in use. Change LANGGRAPH_A2A_PORT or run: make run-app-fresh"; \
	  exit 1; \
	fi && \
	uv run $${MLFLOW_TRACKING_URI:+--extra tracing} python -m a2a_langgraph_crewai.langgraph_a2a_server

run-app: ## Run both A2A servers (Crew in background, LangGraph in foreground)
	@[ -d .venv ] || { echo "ERROR: No .venv — run: make env  (or: uv venv --python 3.12 && uv sync)"; exit 1; }
	@source .venv/bin/activate && set -a && source .env && set +a && \
	CREW_PORT=$${CREW_A2A_PORT:-9100}; LG_PORT=$${LANGGRAPH_A2A_PORT:-9200}; \
	if command -v lsof >/dev/null 2>&1; then \
	  if lsof -ti:$$CREW_PORT >/dev/null 2>&1 || lsof -ti:$$LG_PORT >/dev/null 2>&1; then \
	    echo "ERROR: Port $$CREW_PORT or $$LG_PORT is already in use." && \
	    echo "  Change ports in .env or run: make run-app-fresh" && \
	    exit 1; \
	  fi; \
	fi && \
	echo "==> Starting Crew A2A on port $$CREW_PORT (background)..." && \
	uv run $${MLFLOW_TRACKING_URI:+--extra tracing} python -m a2a_langgraph_crewai.crew_a2a_server & \
	CREW_PID=$$! && \
	trap 'kill $$CREW_PID 2>/dev/null; wait $$CREW_PID 2>/dev/null' EXIT INT TERM && \
	for _ in $$(seq 1 90); do \
	  (echo >/dev/tcp/127.0.0.1/$$CREW_PORT) 2>/dev/null && break; \
	  if ! kill -0 $$CREW_PID 2>/dev/null; then \
	    echo "ERROR: Crew server exited before binding port $$CREW_PORT"; exit 1; \
	  fi; \
	  sleep 0.2; \
	done; \
	(echo >/dev/tcp/127.0.0.1/$$CREW_PORT) 2>/dev/null || { \
	  echo "ERROR: Crew did not listen on port $$CREW_PORT in time"; kill $$CREW_PID 2>/dev/null; exit 1; \
	}; \
	echo "==> Starting LangGraph A2A on port $$LG_PORT (foreground; Ctrl+C stops both)..." && \
	uv run $${MLFLOW_TRACKING_URI:+--extra tracing} python -m a2a_langgraph_crewai.langgraph_a2a_server

run-app-fresh: ## Free default A2A ports and run both servers (see run-app)
	@[ -d .venv ] || { echo "ERROR: No .venv — run: make env  (or: uv venv --python 3.12 && uv sync)"; exit 1; }
	@source .venv/bin/activate && set -a && source .env && set +a && \
	CREW_PORT=$${CREW_A2A_PORT:-9100}; LG_PORT=$${LANGGRAPH_A2A_PORT:-9200}; \
	echo "==> Killing processes on ports $$CREW_PORT and $$LG_PORT (if any)..." && \
	(command -v lsof >/dev/null 2>&1 && lsof -ti:$$CREW_PORT | xargs kill -9 2>/dev/null); true && \
	(command -v lsof >/dev/null 2>&1 && lsof -ti:$$LG_PORT | xargs kill -9 2>/dev/null); true && \
	sleep 0.5 && \
	$(MAKE) run-app

_check-env:
	@set -a && source .env 2>/dev/null && set +a; \
	  missing=""; \
	  for var in $$(sed -n '/^ *required:/,/^ *[a-z]/{ /^ *- /s/^ *- *//p; }' agent.yaml); do \
	    eval val="\$$$$var"; \
	    [ -n "$$val" ] || missing="$$missing $$var"; \
	  done; \
	  [ -z "$$missing" ] || { echo "ERROR: Missing required env vars:$$missing"; exit 1; }

build: _check-env ## Build both image tags locally (same Dockerfile; second tag via tag)
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; }
	@set -a && source .env && set +a && \
	if [ -n "$${CONTAINER_IMAGE_CREW:-}" ] && [ -n "$${CONTAINER_IMAGE_LANGGRAPH:-}" ]; then \
	  CREW="$${CONTAINER_IMAGE_CREW}"; LG="$${CONTAINER_IMAGE_LANGGRAPH}"; \
	elif [ -n "$${CONTAINER_IMAGE:-}" ]; then \
	  _base="$${CONTAINER_IMAGE%%@*}"; _tail="$${_base##*/}"; \
	  if [[ "$$_tail" == *:* ]]; then _img="$${_base%:*}"; else _img="$$_base"; fi; \
	  CREW="$${_img}:crew"; LG="$${_img}:langgraph"; \
	else \
	  echo "ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH in .env"; exit 1; \
	fi && \
	echo "Building $$CREW (then tag -> $$LG)..." && \
	$(CONTAINER_CLI) buildx build --platform linux/amd64 -t "$$CREW" -f Dockerfile . --load && \
	$(CONTAINER_CLI) tag "$$CREW" "$$LG" && \
	echo "Build complete: $$CREW and $$LG"

push: _check-env ## Push both image tags to the registry
	@[ -n "$(CONTAINER_CLI)" ] || { echo "ERROR: neither podman nor docker found in PATH"; exit 1; }
	@set -a && source .env && set +a && \
	if [ -n "$${CONTAINER_IMAGE_CREW:-}" ] && [ -n "$${CONTAINER_IMAGE_LANGGRAPH:-}" ]; then \
	  CREW="$${CONTAINER_IMAGE_CREW}"; LG="$${CONTAINER_IMAGE_LANGGRAPH}"; \
	elif [ -n "$${CONTAINER_IMAGE:-}" ]; then \
	  _base="$${CONTAINER_IMAGE%%@*}"; _tail="$${_base##*/}"; \
	  if [[ "$$_tail" == *:* ]]; then _img="$${_base%:*}"; else _img="$$_base"; fi; \
	  CREW="$${_img}:crew"; LG="$${_img}:langgraph"; \
	else \
	  echo "ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH in .env"; exit 1; \
	fi && \
	echo "Pushing $$CREW and $$LG..." && \
	$(CONTAINER_CLI) push "$$CREW" && $(CONTAINER_CLI) push "$$LG" && \
	echo "Push complete."

deploy: _check-env ## Two-phase Helm deploy (Routes first, then Deployments with public Agent Card URLs)
	@[ -n "$(CONTAINER_CLI)" ] || true
	@set -a && source .env && set +a && \
	if [ -n "$${CONTAINER_IMAGE_CREW:-}" ] && [ -n "$${CONTAINER_IMAGE_LANGGRAPH:-}" ]; then \
	  CREW_REPO="$${CONTAINER_IMAGE_CREW%:*}"; CREW_TAG="$${CONTAINER_IMAGE_CREW##*:}"; \
	  LG_REPO="$${CONTAINER_IMAGE_LANGGRAPH%:*}"; LG_TAG="$${CONTAINER_IMAGE_LANGGRAPH##*:}"; \
	elif [ -n "$${CONTAINER_IMAGE:-}" ]; then \
	  _base="$${CONTAINER_IMAGE%%@*}"; _tail="$${_base##*/}"; \
	  if [[ "$$_tail" == *:* ]]; then _img="$${_base%:*}"; else _img="$$_base"; fi; \
	  CREW_REPO="$$_img"; CREW_TAG="crew"; LG_REPO="$$_img"; LG_TAG="langgraph"; \
	else \
	  echo "ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH in .env"; exit 1; \
	fi && \
	trap 'rm -f .helm-secrets.yaml' EXIT && \
	umask 077 && \
	{ printf 'secrets:\n  apiKey: "%s"\n' "$${API_KEY}"; \
	  [ -z "$${MLFLOW_TRACKING_TOKEN}" ] || printf '  mlflowTrackingToken: "%s"\n' "$${MLFLOW_TRACKING_TOKEN}"; \
	} > .helm-secrets.yaml && \
	echo "=== Helm phase 1: Service, Route, Secret (no Deployments yet) ===" && \
	helm upgrade --install $(AGENT_NAME) $(CHART_DIR) \
	  -f $(VALUES_FILE) \
	  -f .helm-secrets.yaml \
	  --set deploymentsEnabled=false \
	  --set-string image.crew.repository="$$CREW_REPO" \
	  --set-string image.crew.tag="$$CREW_TAG" \
	  --set-string image.langgraph.repository="$$LG_REPO" \
	  --set-string image.langgraph.tag="$$LG_TAG" \
	  --set-string env.BASE_URL="$$BASE_URL" \
	  --set-string env.MODEL_ID="$$MODEL_ID" \
	  $${MLFLOW_TRACKING_URI:+--set-string env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	  $${MLFLOW_EXPERIMENT_NAME:+--set-string env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	  $${MLFLOW_TRACKING_INSECURE_TLS:+--set-string env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
	  $${MLFLOW_WORKSPACE:+--set-string env.MLFLOW_WORKSPACE="$${MLFLOW_WORKSPACE}"} && \
	echo "=== Waiting for OpenShift Route hostnames ===" && \
	CREW_HOST=""; LG_HOST=""; \
	for _ in $$(seq 1 60); do \
	  CREW_HOST=$$(oc get route a2a-crew-agent -o jsonpath='{.spec.host}' 2>/dev/null || true); \
	  LG_HOST=$$(oc get route a2a-langgraph-agent -o jsonpath='{.spec.host}' 2>/dev/null || true); \
	  [ -n "$$CREW_HOST" ] && [ -n "$$LG_HOST" ] && break; \
	  sleep 1; \
	done && \
	if [ -z "$$CREW_HOST" ] || [ -z "$$LG_HOST" ]; then \
	  echo "ERROR: Could not read route hostnames. Check: oc get route"; exit 1; \
	fi && \
	echo "CREW_A2A_PUBLIC_URL=https://$$CREW_HOST" && \
	echo "LANGGRAPH_A2A_PUBLIC_URL=https://$$LG_HOST" && \
	echo "=== Helm phase 2: Deployments with Agent Card URLs ===" && \
	helm upgrade $(AGENT_NAME) $(CHART_DIR) \
	  -f $(VALUES_FILE) \
	  --reuse-values \
	  --set deploymentsEnabled=true \
	  --set-string crewPublicUrl="https://$$CREW_HOST" \
	  --set-string langgraphPublicUrl="https://$$LG_HOST" \
	  $${MLFLOW_TRACKING_URI:+--set-string env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	  $${MLFLOW_EXPERIMENT_NAME:+--set-string env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	  $${MLFLOW_TRACKING_INSECURE_TLS:+--set-string env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
	  $${MLFLOW_WORKSPACE:+--set-string env.MLFLOW_WORKSPACE="$${MLFLOW_WORKSPACE}"} && \
	oc rollout status deployment/a2a-crew-agent --timeout=300s && \
	oc rollout status deployment/a2a-langgraph-agent --timeout=300s && \
	echo "=== Done ===" && oc get route a2a-crew-agent a2a-langgraph-agent

undeploy: ## Remove Helm release (all resources)
	helm uninstall $(AGENT_NAME) --ignore-not-found

dry-run: _check-env ## Render Helm manifests (secrets redacted)
	@set -a && source .env && set +a && \
	if [ -n "$${CONTAINER_IMAGE_CREW:-}" ] && [ -n "$${CONTAINER_IMAGE_LANGGRAPH:-}" ]; then \
	  CREW_REPO="$${CONTAINER_IMAGE_CREW%:*}"; CREW_TAG="$${CONTAINER_IMAGE_CREW##*:}"; \
	  LG_REPO="$${CONTAINER_IMAGE_LANGGRAPH%:*}"; LG_TAG="$${CONTAINER_IMAGE_LANGGRAPH##*:}"; \
	elif [ -n "$${CONTAINER_IMAGE:-}" ]; then \
	  _base="$${CONTAINER_IMAGE%%@*}"; _tail="$${_base##*/}"; \
	  if [[ "$$_tail" == *:* ]]; then _img="$${_base%:*}"; else _img="$$_base"; fi; \
	  CREW_REPO="$$_img"; CREW_TAG="crew"; LG_REPO="$$_img"; LG_TAG="langgraph"; \
	else echo "ERROR: Set CONTAINER_IMAGE or both CONTAINER_IMAGE_CREW and CONTAINER_IMAGE_LANGGRAPH"; exit 1; fi && \
	helm template $(AGENT_NAME) $(CHART_DIR) \
	  -f $(VALUES_FILE) \
	  --set secrets.apiKey=REDACTED \
	  --set deploymentsEnabled=true \
	  --set-string crewPublicUrl="https://crew.example.com" \
	  --set-string langgraphPublicUrl="https://langgraph.example.com" \
	  --set-string image.crew.repository="$$CREW_REPO" \
	  --set-string image.crew.tag="$$CREW_TAG" \
	  --set-string image.langgraph.repository="$$LG_REPO" \
	  --set-string image.langgraph.tag="$$LG_TAG" \
	  --set-string env.BASE_URL="$$BASE_URL" \
	  --set-string env.MODEL_ID="$$MODEL_ID" \
	  $${MLFLOW_TRACKING_URI:+--set-string env.MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI}"} \
	  $${MLFLOW_TRACKING_TOKEN:+--set secrets.mlflowTrackingToken="REDACTED"} \
	  $${MLFLOW_EXPERIMENT_NAME:+--set-string env.MLFLOW_EXPERIMENT_NAME="$${MLFLOW_EXPERIMENT_NAME}"} \
	  $${MLFLOW_TRACKING_INSECURE_TLS:+--set-string env.MLFLOW_TRACKING_INSECURE_TLS="$${MLFLOW_TRACKING_INSECURE_TLS}"} \
	  $${MLFLOW_WORKSPACE:+--set-string env.MLFLOW_WORKSPACE="$${MLFLOW_WORKSPACE}"}
