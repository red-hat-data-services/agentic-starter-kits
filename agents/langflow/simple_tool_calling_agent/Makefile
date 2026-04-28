SHELL          := bash
COMPOSE_FILE   := local/podman-compose.yml
ENV_FILE       := local/.env
MODEL          ?= qwen2.5:7b

.PHONY: init ollama llama-server run stop clean status logs help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

init: ## Create local/.env from .env.example and generate secrets
	@if [ ! -f $(ENV_FILE) ]; then \
	  cp .env.example $(ENV_FILE) && echo "Created local/.env from .env.example"; \
	else \
	  echo "local/.env already exists — skipping"; \
	fi
	@if ! grep -q '^LANGFUSE_ADMIN_PASSWORD=.\+' $(ENV_FILE) 2>/dev/null; then \
	  GENERATED_PWD=$$(openssl rand -base64 12) && \
	  sed -i.bak "s/^LANGFUSE_ADMIN_PASSWORD=.*/LANGFUSE_ADMIN_PASSWORD=$$GENERATED_PWD/" $(ENV_FILE) && \
	  rm -f $(ENV_FILE).bak && \
	  echo "Generated Langfuse admin password."; \
	fi
	@if ! grep -q '^LANGFUSE_ENCRYPTION_KEY=.\+' $(ENV_FILE) 2>/dev/null; then \
	  GENERATED_KEY=$$(openssl rand -hex 32) && \
	  sed -i.bak "s/^LANGFUSE_ENCRYPTION_KEY=.*/LANGFUSE_ENCRYPTION_KEY=$$GENERATED_KEY/" $(ENV_FILE) && \
	  rm -f $(ENV_FILE).bak && \
	  echo "Generated Langfuse encryption key."; \
	fi

ollama: ## Install Ollama, start it, and pull models
	@if command -v ollama >/dev/null 2>&1; then \
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
	  echo "Done. Run 'make llama-server' to start the Llama Stack server."

llama-server: ## Install llama-stack and start Llama Stack server
	@if [ ! -d .venv ]; then \
	  echo "==> Creating virtual environment..." && \
	  uv venv .venv --python 3.12; \
	fi && \
	source .venv/bin/activate && \
	  echo "==> Installing llama-stack..." && \
	  uv pip install "llama-stack==0.5.0" "llama-stack-api==0.5.0" ollama && \
	  echo "==> Killing any existing process on port 8321..." && \
	  lsof -ti:8321 | xargs kill -9 2>/dev/null; true && \
	  echo "==> Starting Llama Stack server on port 8321..." && \
	  llama stack run ../../../run_llama_server.yaml

run: init ## Start the local Langflow stack (Langflow + PostgreSQL + Langfuse)
	@./deploy-local.sh

stop: ## Stop services (data preserved)
	@./cleanup-local.sh

clean: ## Stop services and remove all data
	@./cleanup-local.sh --force

status: ## Show status of running services
	@podman-compose -f $(COMPOSE_FILE) ps

logs: ## Tail logs from all services
	@podman-compose -f $(COMPOSE_FILE) logs -f
