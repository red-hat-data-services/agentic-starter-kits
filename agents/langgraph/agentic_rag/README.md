<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# RAG Agent

</div>

---

## What this agent does

RAG (Retrieval-Augmented Generation) agent that indexes documents in a vector store and retrieves relevant
chunks to augment the LLM's answers with your own data. Built with LangGraph, LangChain, and LlamaStack.
Supports Milvus Lite (local) and pgvector (OpenShift) as vector store backends.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) — for local container builds (Option A)
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) — for
  OpenShift deployment
- [Helm](https://helm.sh/) — for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell — on Windows,
  use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended)
  or [Git Bash](https://git-scm.com/downloads)

## Local Development

#### Initiating base

`make init` creates a `.env` file from `.env.example`. Set your environment variables in the `.env` file.

```bash
cd agents/langgraph/agentic_rag
make init
```

#### Tracing (optional)

Tracing is optional. If MLflow tracing is required, enable it by uncommenting and setting the following environment variables in the `.env` file.

##### Tracing with a local MLflow server

```ini
MLFLOW_TRACKING_URI="http://localhost:5000"
MLFLOW_EXPERIMENT_NAME="langgraph-agentic-rag"
MLFLOW_HTTP_REQUEST_TIMEOUT=2
MLFLOW_HTTP_REQUEST_MAX_RETRIES=0
```

Then start the MLflow server in a separate terminal:

```bash
# Start the MLflow server
uv run --extra tracing mlflow server --port 5000
```

When `MLFLOW_TRACKING_URI` is set, `make run-app` and `make run-cli` will automatically install the tracing dependency.

##### Tracing with an OpenShift MLflow server

To enable tracing and logging with MLflow on your OpenShift cluster, add the following environment variables to your `.env` file:

```ini
MLFLOW_TRACKING_URI="https://<openshift-dashboard-url>/mlflow"
MLFLOW_TRACKING_TOKEN="<your-openshift-token>"
MLFLOW_EXPERIMENT_NAME="langgraph-agentic-rag"
MLFLOW_TRACKING_INSECURE_TLS="true"
MLFLOW_WORKSPACE="default"
```

**Notes:**
- `MLFLOW_TRACKING_URI` - URL of your MLflow server. For local development, use `http://localhost:5000`. If using MLflow on an OpenShift cluster, replace `<openshift-dashboard-url>` with your cluster's data science gateway URL.
- `MLFLOW_TRACKING_TOKEN` - Required for OpenShift only. Your OpenShift authentication token, obtained from the OpenShift console.
- `MLFLOW_EXPERIMENT_NAME` - A descriptive name for your experiment (e.g., "LangGraph Agentic RAG Demo")
- `MLFLOW_TRACKING_INSECURE_TLS` - Required for OpenShift only. Set to `"true"` if your cluster does not use trusted certificates.
- `MLFLOW_WORKSPACE` - Required for OpenShift only. Project name.

- Tracing is optional; if you do not set `MLFLOW_TRACKING_URI`, the application will run without MLflow logging.

- If `MLFLOW_TRACKING_URI` is set, the application will attempt to connect to the MLflow server at startup. If the server is unreachable, the application will log a warning and continue running without tracing.

- You can control how long the application waits for the MLflow server by setting `MLFLOW_HEALTH_CHECK_TIMEOUT` (in seconds, default: `5`).

#### RAG Configuration

In addition to the model configuration, this agent requires RAG-specific settings in your `.env` file:

```ini
EMBEDDING_MODEL=ollama/embeddinggemma:latest
EMBEDDING_DIMENSION=768
VECTOR_STORE_ID=
VECTOR_STORE_PROVIDER=milvus
VECTOR_STORE_PATH=/absolute/path/to/milvus_data/milvus_lite.db
DOCS_TO_LOAD=./data/sample_knowledge.txt
```

**Notes:**

- `EMBEDDING_MODEL` - Model used for generating document embeddings. For local use with Ollama, pull the model first: `ollama pull embeddinggemma:latest`
- `EMBEDDING_DIMENSION` - Dimension of the embedding vectors (default: `768`). Must match the embedding model's output dimension.
- `VECTOR_STORE_ID` - Identifier for the vector store collection. If left empty, a new collection will be created when loading documents.
- `VECTOR_STORE_PROVIDER` - Vector store backend: `milvus` for local development (default), `pgvector` for OpenShift deployments.
- `VECTOR_STORE_PATH` - Absolute path where the Milvus Lite database will be stored. Not used when `VECTOR_STORE_PROVIDER=pgvector`.
- `DOCS_TO_LOAD` - Path to the text file containing documents to load into the vector store. A sample file is provided at `./data/sample_knowledge.txt`.

#### Creating environment

Now you will remove old .venv and create new. Next dependencies will be installed.

```bash
make env
```

#### Setup Ollama

This will install ollama if it is not installed already. Then pull needed models for local work.
The default model is `llama3.1:8b`. To use a different model, pass `MODEL=`:
`make ollama MODEL=llama3.2:3b`

This also pulls the embedding model (`embeddinggemma:latest`) required for RAG.

```bash
make ollama
```

#### Run llama server

> **Keep this terminal open** – the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.

```bash
make llama-server
```

#### Load documents into vector store

Before running the agent, you need to load documents into the vector store.

If you do not have a `VECTOR_STORE_ID`, you can create one by running the document loader:

```bash
make load-docs
```

This will:

- Read documents from the file specified in `DOCS_TO_LOAD`
- Split documents into chunks (512 characters with 128 overlap by default)
- Generate embeddings using the model specified in `EMBEDDING_MODEL`
- Create a new vector store (using `VECTOR_STORE_PROVIDER`, defaults to `milvus` for local)
- Store chunks in the vector store
- Automatically write the new `VECTOR_STORE_ID` back to your `.env` file

#### Run the interactive web application

> **Keep this terminal open** – the app needs to keep running.
> You should see output indicating the app started on `http://localhost:8000`.

```bash
cd agents/langgraph/agentic_rag
make run-app           # fails if port is already in use and print steps TO-DO
```

#### Interactive CLI

For terminal-based testing without a browser:

```bash
cd agents/langgraph/agentic_rag
make run-cli
```

This launches an interactive prompt where you can pick predefined questions or type your own. Tool calls and results are
displayed inline with colored output.

## Deploying to OpenShift

### Setup

```bash
cd agents/langgraph/agentic_rag
make init
```

### Configuration

Edit `.env` with your model endpoint, RAG configuration, and container image.

#### Using a LlamaStack server on the cluster

If a LlamaStack server is already deployed on the cluster (e.g., in the `llama-serving` namespace), use its
external route URL so both LLM and vector store operations go through LlamaStack:

```ini
API_KEY=not-needed
BASE_URL=https://llamastack-route-host/v1
MODEL_ID=vllm//mnt/models
CONTAINER_IMAGE=quay.io/your-username/langgraph-agentic-rag:latest

# RAG Configuration
EMBEDDING_MODEL=sentence-transformers/nomic-ai/nomic-embed-text-v1.5
EMBEDDING_DIMENSION=768
VECTOR_STORE_ID=
VECTOR_STORE_PROVIDER=pgvector
DOCS_TO_LOAD=./data/sample_knowledge.txt
```

To discover the LlamaStack route URL and available models on your cluster:

```bash
# Get the LlamaStack route
oc get route -n llama-serving llamastack -o jsonpath='{.spec.host}'

# Check available models
curl -s https://<route-host>/v1/models | python3 -m json.tool
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator. Use `not-needed` for LlamaStack servers that don't require auth.
- `BASE_URL` - should end with `/v1`. For LlamaStack on the cluster, use the external route URL.
- `MODEL_ID` - model identifier available on your endpoint
- `VECTOR_STORE_PROVIDER` - vector store backend configured in your LlamaStack server. Use `pgvector` or `milvus` depending on your LlamaStack deployment.
- `CONTAINER_IMAGE` -- full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/langgraph-agentic-rag:latest`
    - Docker Hub: `docker.io/your-username/langgraph-agentic-rag:latest`
    - GHCR: `ghcr.io/your-org/langgraph-agentic-rag:latest`

  > **Note:** OpenShift must be able to pull the container image. Make the image **public**, or configure
  an [image pull secret](https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html)
  for private registries.

### Loading Documents into the Vector Store (OpenShift)

Before deploying the agent, load documents into the LlamaStack vector store. Run the loader script
locally, pointing it at the LlamaStack server's external route (the same `BASE_URL` used in your `.env`):

```bash
uv run python data/load_documents.py
```

The script creates a new vector store, prints its ID, and writes the `VECTOR_STORE_ID` back to your `.env` file automatically.

### Building the Container Image

Login to OC

```bash
oc login -u "login" -p "password" https://super-link-to-cluster:111
```

Login ex. Docker

```bash
docker login -u='login' -p='password' quay.io
```

#### Option A: Build locally and push to a registry

Requires Podman (or Docker) and a registry account (e.g., Quay.io).

```bash
make build    # builds the image locally
make push     # pushes to the registry specified in CONTAINER_IMAGE
```

#### Option B: Build in-cluster via OpenShift BuildConfig

No Podman, Docker, or registry account needed -- just the `oc` CLI.

```bash
make build-openshift
```

After the build completes, set `CONTAINER_IMAGE` in your `.env` to the internal registry URL printed after the build.

### Deploying

#### Preview manifests (`make dry-run`)

```bash
make dry-run          # preview rendered Helm manifests (secrets redacted)
```

#### Deploy (`make deploy`)

```bash
make deploy
```

#### Verify deployment

After deploying, the application may take about a minute to become available while the pod starts up.

The route URL is printed after `make deploy`. You can also retrieve it manually:

```bash
oc get route langgraph-agentic-rag -o jsonpath='{.spec.host}'
```

#### Remove deployment (`make undeploy`)

```bash
make undeploy
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for more details.

## Tests

```bash
make test
```

## API Endpoints

### POST /chat/completions

Non-streaming:

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is LangChain?"}], "stream": false}'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is LangChain?"}], "stream": true}'
```

Pretty Printed Stream:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is LangChain?"}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

### GET /health

```bash
curl http://localhost:8000/health
```

## How It Works

This agent implements a Retrieval-Augmented Generation (RAG) pattern:

1. **Document Indexing**: Documents are loaded from a text file, split into chunks, and embedded using the configured embedding model. The embeddings are stored in a vector database via LlamaStack (supports Milvus and pgvector backends, configurable via `VECTOR_STORE_PROVIDER`).

2. **Query Processing**: When the user asks a question, the agent searches the vector store through LlamaStack for the most relevant document chunks.

3. **Augmented Generation**: The retrieved chunks are provided as context to the LLM, which generates an answer grounded in the relevant documents. This reduces hallucination and allows the model to answer questions about your specific data.

The agent uses LangGraph to orchestrate the retrieval and generation steps, LangChain for the LLM integration, and LlamaStack for vector store operations.

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Documentation](https://python.langchain.com/)
- [Llama Stack Documentation](https://llama-stack.readthedocs.io/)
- [Milvus Documentation](https://milvus.io/docs)
