<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# Agentic RAG Agent

</div>

---

## What this agent does

RAG agent that indexes documents in a vector store (Milvus) and retrieves relevant chunks to augment the LLM's answers
with your own data.

---

## Quick Start

```bash
cd agents/langgraph/agentic_rag
make init        # creates .env from .env.example
# Edit .env with required vars (see below)
make run         # starts on http://localhost:8080
```

## Configuration

### Local

```
API_KEY=not-needed
BASE_URL=http://localhost:8321/v1
MODEL_ID=ollama/llama3.2:3b
EMBEDDING_MODEL=ollama/embeddinggemma:latest
VECTOR_STORE_ID=your-vector-store-id
VECTOR_STORE_PATH=/path/to/milvus_data/milvus_lite.db
```

See [Local Development](../../../docs/local-development.md) for Ollama + Llama Stack setup.

### OpenShift / Remote API

```
API_KEY=your-api-key-here
BASE_URL=https://your-model-endpoint.com/v1
MODEL_ID=llama-3.1-8b-instruct
EMBEDDING_MODEL=your-embedding-model
VECTOR_STORE_ID=your-vector-store-id
CONTAINER_IMAGE=quay.io/your-username/langgraph-agentic-rag:latest
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `EMBEDDING_MODEL` - model used for generating document embeddings (requires `ollama pull embeddinggemma:latest` for local usage)
- `VECTOR_STORE_PATH` - absolute path where the Milvus Lite database will be stored
- `DOCS_TO_LOAD` - path to text file containing documents to load into the vector store (default: `./data/sample_knowledge.txt`)
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/langgraph-agentic-rag:latest`
    - Docker Hub: `docker.io/your-username/langgraph-agentic-rag:latest`
    - GHCR: `ghcr.io/your-org/langgraph-agentic-rag:latest`

## Load Documents into Vector Store

**IMPORTANT**:
Before running the agent, you must have your Vector Store ID pasted into `VECTOR_STORE_ID=""`.
If you do not have a `VECTOR_STORE_ID`, you can create one with the `load_documents.py` script.

For local usage, first pull the embedding model:

```bash
ollama pull embeddinggemma:latest
```

Run the document loader:

```bash
uv run python data/load_documents.py
```

This will:

- Read documents from `data/sample_knowledge.txt` (or the path in `DOCS_TO_LOAD`)
- Split documents into chunks (512 characters with 128 overlap by default)
- Generate embeddings using the model specified in `EMBEDDING_MODEL`
- Store chunks in the Milvus vector database at `VECTOR_STORE_PATH`

## Deploying to OpenShift

```bash
# Option A: Build locally with Podman (or Docker) and push to a registry
make build            # builds container image locally
make push             # pushes image to registry
make deploy           # deploys via Helm (includes volume mount for vector store)

# Option B: Build in-cluster on OpenShift (no Podman/Docker needed)
make build-openshift  # builds image via OpenShift BuildConfig
make deploy

# Preview rendered manifests before deploying
make dry-run
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for details.

### Testing on OpenShift

Get the route URL:

```bash
oc get route langgraph-agentic-rag -o jsonpath='{.spec.host}'
```

Replace `http://localhost:8080` with `https://<YOUR_ROUTE_URL>` in the API examples below.

## API Endpoints

### POST /chat/completions

Non-streaming:

```bash
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is LangChain?"}], "stream": false}'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is LangChain?"}], "stream": true}'
```

Pretty Printed Stream:

```bash
curl -sN -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is LangChain?"}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

### GET /health

```bash
curl http://localhost:8080/health
```

## Playground UI

A browser-based chat interface is served directly by the agent at the root URL — no separate process needed.

### Running the Playground

Start the agent and open the root URL in your browser:

```bash
uvicorn main:app --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

A green dot in the header means the agent is connected and ready. Type a message and press **Enter** to send.

When deployed to OpenShift, the playground is available at the route URL.

### Standalone Flask Playground (alternative)

You can also run the playground as a separate Flask app if needed:

```bash
uv pip install flask
```

```bash
# Terminal 1: Start the agent
uvicorn main:app --port 8000

# Terminal 2: Start the playground
flask --app playground/app run --port 5001
```

| Variable    | Default                  | Description                     |
|-------------|--------------------------|---------------------------------|
| `AGENT_URL` | `http://localhost:8000`  | URL of the running agent API    |

If the agent runs on a different host or port:

```bash
AGENT_URL=https://your-agent-url flask --app playground/app run --port 5001
```

## Tests

```bash
make test
```

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Milvus Documentation](https://milvus.io/docs)
- [Llama Stack Documentation](https://llama-stack.readthedocs.io/)
