# Local Development

Run agents locally using Ollama and OGX for model serving, or connect to any OpenAI-compatible API.

**Windows users:** The Makefiles require a bash-compatible shell. Use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install), [Git Bash](https://git-scm.com/downloads), or a similar environment.

## Option A: Ollama + OGX (fully local)

### 1. Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

For other platforms, see the [Ollama docs](https://ollama.com/).

Start the Ollama service (keep this terminal open):

```bash
ollama serve
```

### 2. Pull a Model

```bash
ollama pull llama3.2:3b
```

For RAG agents that need embeddings:

```bash
ollama pull embeddinggemma:latest
```

### 3. Start OGX Server

From a standard agent directory (e.g., `agents/langgraph/templates/react_agent`):

```bash
cd agents/langgraph/templates/react_agent   # or any other standard agent
make init
make env
make ogx-server
```

The `make ogx-server` target installs OGX, starts it with `run_ogx_server.yaml`, and serves requests on `http://localhost:8321`.

### 4. Configure and Run an Agent

```bash
cd agents/langgraph/templates/react_agent   # or any other agent
```

Edit `.env`:

```ini
API_KEY=dummy
BASE_URL=http://localhost:8321/v1
MODEL_ID=llama3.2:3b
```

```bash
make run-app
```

The agent starts on `http://localhost:8000`.

> **Note:** Non-standard agents like `agents/langflow/templates/simple_tool_calling_agent` use different local run commands. Follow the agent-specific README when its Makefile does not provide the standard `make env` / `make ogx-server` / `make run-app` workflow.

## Option B: OpenAI-Compatible API

If you have an OpenAI-compatible API endpoint (OpenAI, Azure OpenAI, vLLM, etc.), just point `BASE_URL` and `API_KEY` at it:

```ini
API_KEY=sk-...
BASE_URL=https://api.openai.com/v1
MODEL_ID=gpt-4o
```

## Testing the Agent

```bash
# Health check
curl http://localhost:8000/health

# Non-streaming
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}], "stream": false}'

# Streaming
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}], "stream": true}'
```

## Running Tests

```bash
cd agents/langgraph/templates/react_agent
make test
```

## Dependencies

All agents use [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

To install an agent's dependencies locally:

```bash
cd agents/langgraph/templates/react_agent
uv pip install -e ".[dev]"
```
