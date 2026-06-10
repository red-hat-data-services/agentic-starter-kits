# Local Development

Run agents locally using Ollama and Llama Stack for model serving, or connect to any OpenAI-compatible API.

**Windows users:** The Makefiles require a bash-compatible shell. Use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install), [Git Bash](https://git-scm.com/downloads), or a similar environment.

## Option A: Ollama + Llama Stack (fully local)

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

### 3. Start Llama Stack Server

From your agent directory (e.g., `agents/llamaindex/templates/websearch_agent`):

```bash
# Install llama-stack and its provider dependencies (ollama, milvus)
uv tool install llama-stack \
  --with ollama \
  --with "pymilvus>=2.4.10" \
  --with "milvus-lite>=2.5.1" \
  --with chardet \
  --with pypdf \
  --with "setuptools<82"

# Create milvus data directory (required by run_llama_server.yaml)
mkdir -p ../../../milvus_data

# Start the server
llama stack run ../../../run_llama_server.yaml
```

The server starts on `http://localhost:8321`.

### 4. Configure and Run an Agent

```bash
cd agents/langgraph/templates/react_agent   # or any other agent
make init                          # creates .env
```

Edit `.env`:

```ini
API_KEY=dummy
BASE_URL=http://localhost:8321/v1
MODEL_ID=llama3.2:3b
```

```bash
make run
```

The agent starts on `http://localhost:8000`.

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
