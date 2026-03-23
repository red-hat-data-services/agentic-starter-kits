# Local Development

Run agents locally using Ollama and Llama Stack for model serving, or connect to any OpenAI-compatible API.

## Option A: Ollama + Llama Stack (fully local)

### 1. Install Ollama

Follow the [Ollama docs](https://docs.ollama.com/) for your platform.

### 2. Pull a Model

```bash
ollama pull llama3.2:3b
```

For RAG agents that need embeddings:

```bash
ollama pull embeddinggemma:latest
```

### 3. Start Llama Stack Server

```bash
pip install llama-stack
llama stack run infrastructure/llama-stack/run_llama_server.yaml
```

The server starts on `http://localhost:8321`.

### 4. Configure and Run an Agent

```bash
cd agents/langgraph/react_agent   # or any other agent
make init                          # creates .env
```

Edit `.env`:

```
API_KEY=dummy
BASE_URL=http://localhost:8321/v1
MODEL_ID=llama3.2:3b
```

```bash
make run
```

The agent starts on `http://localhost:8080`.

## Option B: OpenAI-Compatible API

If you have an OpenAI-compatible API endpoint (OpenAI, Azure OpenAI, vLLM, etc.), just point `BASE_URL` and `API_KEY` at it:

```
API_KEY=sk-...
BASE_URL=https://api.openai.com/v1
MODEL_ID=gpt-4o
```

## Testing the Agent

```bash
# Health check
curl http://localhost:8080/health

# Non-streaming
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}], "stream": false}'

# Streaming
curl -sN -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}], "stream": true}'
```

## Running Tests

```bash
cd agents/langgraph/react_agent
make test
```

## Building Container Images Locally

The Makefiles auto-detect [Podman](https://podman.io/) (preferred) or Docker for container builds:

```bash
make build    # builds image locally using podman (or docker)
make push     # pushes image to registry
```

To install Podman, see [podman.io/docs/installation](https://podman.io/docs/installation). On RHEL/Fedora it is pre-installed.

## Dependencies

All agents use [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

To install an agent's dependencies locally:

```bash
cd agents/langgraph/react_agent
uv pip install -e ".[dev]"
```
