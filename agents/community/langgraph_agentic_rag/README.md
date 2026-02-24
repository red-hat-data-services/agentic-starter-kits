<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.png)

# Agentic RAG Agent

</div>

---

### Preconditions:

- You need to copy/paste .env file and change its values to yours
- Decide what way you want to go `local` or `RH OpenShift Cluster` and fill needed values
- Use `./init.sh` that will add those values from .env to environment variables
- **RAG-specific**: You need to load documents into the vector store before using the agent (see below)

Copy .env file

```bash
cp template.env agents/community/langgraph_agentic_rag/.env
```

#### Local

Edit the `.env` file with your local configuration:

```
BASE_URL=http://localhost:8321
MODEL_ID=ollama/llama3.2:3b
API_KEY=not-needed
CONTAINER_IMAGE=not-needed

# RAG-specific Configuration
VECTOR_STORE_PATH=/absolute/path/to/milvus_data/milvus_lite.db
EMBEDDING_MODEL=ollama/embeddinggemma:latest
DOCS_TO_LOAD=./data/sample_knowledge.txt
PORT=8000
```

**Notes:**

- `VECTOR_STORE_PATH` - Absolute path where Milvus Lite database will be stored
- `EMBEDDING_MODEL` - Model used for generating document embeddings (requires `ollama pull embeddinggemma:latest`)
- `DOCS_TO_LOAD` - Path to text file containing documents to load into vector store
- `PORT` - FastAPI server port (default: 8000)

#### OpenShift Cluster

Edit the `.env` file and fill in all required values:

```
API_KEY=your-api-key-here
BASE_URL=https://your-llama-stack-distribution.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/langgraph-agentic-rag:latest

# RAG-specific Configuration
VECTOR_STORE_PATH=/data/milvus_lite.db
EMBEDDING_MODEL=your-embedding-model
DOCS_TO_LOAD=./data/sample_knowledge.txt
PORT=8000
```

**Notes:**

- `API_KEY` - contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - contact your cluster administrator
- `CONTAINER_IMAGE` - full image path where the agent container will be pushed and pulled from.
  The image is built locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:
    - Quay.io: `quay.io/your-username/langgraph-agentic-rag:latest`
    - Docker Hub: `docker.io/your-username/langgraph-agentic-rag:latest`
    - GHCR: `ghcr.io/your-org/langgraph-agentic-rag:latest`

Go to agent dir

```bash
cd agents/community/langgraph_agentic_rag
```

Make scripts executable

```bash
chmod +x init.sh
```

Add values from .env to environment variables

```bash
./init.sh
```

---

## Local usage (Ollama + LlamaStack Server)

Create package with agent and install it to venv

```bash
uv pip install -e .
```

```bash
uv pip install ollama
```

```bash
#brew install ollama
# or
curl -fsSL https://ollama.com/install.sh | sh
```

Pull Required Models (including embedding model for RAG)

```bash
ollama pull llama3.2:3b
ollama pull embeddinggemma:latest
```

Start Ollama Service

```bash
ollama serve
```

> **Keep this terminal open!**\
> Ollama needs to keep running.

Start LlamaStack Server

```bash
llama stack run ../../../run_llama_server.yaml
```

> **Keep this terminal open** - the server needs to keep running.\
> You should see output indicating the server started on `http://localhost:8321`.

Create package with agent and install it to venv

```bash
uv pip install -e .
```

### Load Documents into Vector Store

**IMPORTANT**: Before running the agent, you must load documents into the vector store.

Run the document loader:

```bash
python data/load_documents.py
```

This will:

- Read documents from the file specified in `DOCS_TO_LOAD` environment variable
- Split documents into chunks (512 characters with 128 overlap by default)
- Generate embeddings using the model specified in `EMBEDDING_MODEL`
- Store chunks in the Milvus Lite vector database at `VECTOR_STORE_PATH`

**Adding your own documents:**

1. Create a text file with your content (e.g., `my_documents.txt`)
2. Update `.env`:
   ```env
   DOCS_TO_LOAD=./data/my_documents.txt
   ```
3. Re-run the document loader:
   ```bash
   cd data
   python load_documents.py
   ```

**Customizing chunk size:**

Edit `load_documents.py` to adjust chunking parameters:

```python
load_and_index_documents(
    chunk_size=512,  # Size of text chunks (default: 512)
    chunk_overlap=128,  # Overlap between chunks (default: 128)
)
```

**Recommended chunk sizes:**

- Technical documentation: 512-1024 characters
- Narrative text: 256-512 characters
- Code snippets: 128-256 characters

**Troubleshooting vector store:**

If you encounter issues with the vector store:

1. Delete the contents of the `milvus_data` folder
2. Re-run `python load_documents.py` to recreate it

### Run the example:

```bash
cd ..
uv run agents/community/langgraph_agentic_rag/examples/execute_ai_service_locally.py
```

# Deployment on RedHat OpenShift Cluster

Login to OC

```bash
oc login -u "login" -p "password" https://super-link-to-cluster:111
```

Login ex. Docker

```bash
docker login -u='login' -p='password' quay.io
```

Make deploy file executable

```bash
chmod +x deploy.sh
```

Build image and deploy Agent

```bash
./deploy.sh
```

This will:

- Create Kubernetes secret for API key
- Build and push the Docker image
- Deploy the agent to OpenShift
- Create Service and Route

COPY the route URL and PASTE into the CURL below

```bash
oc get route langgraph-agentic-rag -o jsonpath='{.spec.host}'
```

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is LangChain?"}'
```

## Agent-Specific Documentation

### Architecture

The RAG workflow consists of three main steps:

1. **Agent Node**: Decides whether to retrieve information based on the user's query
2. **Retrieve Node**: If needed, retrieves relevant documents from the vector store
3. **Generate Node**: Generates a final answer based on retrieved context

```
START → Agent → [Decision] → Retrieve → Generate → END
                    ↓
                   END (if no retrieval needed)
```

### Features

- **Agentic RAG Workflow**: The agent autonomously decides when to retrieve information
- **Llama Stack Integration**: Unified model serving with Ollama for local LLM inference
- **Milvus Lite Vector Store**: High-performance vector database with easy migration to production Milvus
- **FastAPI Service**: REST API with `/chat` and `/health` endpoints
- **Tool-based Retrieval**: LangGraph tool integration for seamless retrieval
- **Document Loader**: Easy document ingestion from text files with customizable chunking

### Key Differences from Base Agents

This RAG agent extends the base LangGraph agent with:

1. **Retrieval Capability**: Automatic knowledge base search via Llama Stack
2. **Multi-step Workflow**: Agent → Retrieve → Generate pattern
3. **Vector Store Integration**: Milvus Lite-based document storage and retrieval
4. **Context-aware Generation**: Answers based on retrieved documents with relevance checking
5. **Embedding Model Requirement**: Requires separate embedding model for document vectorization

### Additional Resources

- https://langchain-ai.github.io/langgraph/
- https://llama-stack.readthedocs.io/
- https://ollama.com/docs
- https://milvus.io/docs