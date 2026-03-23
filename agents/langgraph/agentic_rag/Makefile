AGENT_NAME     := $(shell python3 -c "import re; print(re.search(r'^name:\s*(.+)', open('agent.yaml').read(), re.M).group(1).strip())")
CHART_DIR      := ../../../charts/agent
VALUES_FILE    := values.yaml
CONTAINER_CLI  := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)

.PHONY: init run build push build-openshift deploy undeploy test dry-run help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

init: ## Copy .env.example to .env for configuration
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — edit it with your configuration"; else echo ".env already exists — skipping"; fi

run: ## Run agent locally with hot-reload
	@set -a && source .env && set +a && \
	  uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload

build: ## Build container image locally (podman/docker)
	@source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  $(CONTAINER_CLI) build --platform linux/amd64 -t "$${CONTAINER_IMAGE}" -f Dockerfile .

push: ## Push container image to registry
	@source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  $(CONTAINER_CLI) push "$${CONTAINER_IMAGE}"

build-openshift: ## Build image in-cluster via OpenShift BuildConfig (no podman/docker needed)
	@oc new-build --strategy=docker --binary --name=$(AGENT_NAME) --to=$(AGENT_NAME):latest 2>/dev/null || true
	@oc start-build $(AGENT_NAME) --from-dir=. --follow

_check-env:
	@set -a && source .env 2>/dev/null && set +a; \
	  python3 -c "import yaml,os,sys; \
	    data=yaml.safe_load(open('agent.yaml')); \
	    required=data.get('env',{}).get('required',[]); \
	    missing=[v for v in required if not os.environ.get(v)]; \
	    sys.exit('ERROR: Missing required env vars: '+', '.join(missing)) if missing else None"

deploy: _check-env ## Deploy to OpenShift/K8s via Helm
	@source .env && \
	  [ -n "$${CONTAINER_IMAGE}" ] || { echo "ERROR: CONTAINER_IMAGE is not set in .env"; exit 1; } && \
	  IMAGE_REPO="$${CONTAINER_IMAGE%:*}" && \
	  IMAGE_TAG="$${CONTAINER_IMAGE##*:}" && \
	  trap 'rm -f .helm-secrets.yaml' EXIT && \
	  printf 'secrets:\n  apiKey: "%s"\n' "$${API_KEY}" > .helm-secrets.yaml && \
	  helm upgrade --install $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    -f .helm-secrets.yaml \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" \
	    --set env.EMBEDDING_MODEL="$${EMBEDDING_MODEL}" \
	    --set env.VECTOR_STORE_ID="$${VECTOR_STORE_ID}"

dry-run: _check-env ## Render Helm templates without deploying
	@source .env && \
	  IMAGE_REPO="$${CONTAINER_IMAGE%:*}" && \
	  IMAGE_TAG="$${CONTAINER_IMAGE##*:}" && \
	  helm template $(AGENT_NAME) $(CHART_DIR) \
	    -f $(VALUES_FILE) \
	    --set secrets.apiKey="REDACTED" \
	    --set image.repository="$${IMAGE_REPO}" \
	    --set image.tag="$${IMAGE_TAG}" \
	    --set env.BASE_URL="$${BASE_URL}" \
	    --set env.MODEL_ID="$${MODEL_ID}" \
	    --set env.EMBEDDING_MODEL="$${EMBEDDING_MODEL}" \
	    --set env.VECTOR_STORE_ID="$${VECTOR_STORE_ID}"

undeploy: ## Remove deployment from cluster
	helm uninstall $(AGENT_NAME)

test: ## Run tests
	uv run --extra dev python -m pytest tests/
