# LangGraph Agentic RAG

A production-ready Retrieval-Augmented Generation (RAG) agent built with LangGraph that intelligently retrieves information from a Milvus Lite vector store and generates context-aware responses using Llama Stack and Ollama.

## Quick Links

- 🚀 **[Quick Start](#quick-start)** - Get running in 8 steps
- 📖 **[Detailed Guide](./QUICKSTART.md)** - Comprehensive setup with troubleshooting
- 🔧 **[Configuration](#configuration-reference)** - Environment variables and settings
- 🎯 **[API Endpoints](#api-endpoints)** - REST API documentation

## Features

- **Agentic RAG Workflow**: The agent autonomously decides when to retrieve information
- **Llama Stack Integration**: Unified model serving with Ollama for local LLM inference
- **Milvus Lite Vector Store**: High-performance vector database with easy migration to production Milvus
- **FastAPI Service**: REST API with `/chat` and `/health` endpoints
- **Tool-based Retrieval**: LangGraph tool integration for seamless retrieval
- **Document Loader**: Easy document ingestion from text files with customizable chunking

## Architecture

The RAG workflow consists of three main steps:

1. **Agent Node**: Decides whether to retrieve information based on the user's query
2. **Retrieve Node**: If needed, retrieves relevant documents from the vector store
3. **Generate Node**: Generates a final answer based on retrieved context

```
START → Agent → [Decision] → Retrieve → Generate → END
                    ↓
                   END (if no retrieval needed)
```

# Use Agent Locally

### Installation Script
Run this script to set up stuff:

```bash
git clone <repository-url>
cd Agentic-Starter-Kits
```
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```
If you want to install ollama you need to install app from [Ollama site](https://ollama.com/) or via [Brew](https://formulae.brew.sh/formula/ollama#default)

```bash
#brew install ollama
# or
#curl -fsSL https://ollama.com/install.sh | sh
```

**Install Llama Stack**:

```bash
pip install llama-stack llama-stack-client
```

### Setup Instructions

**Step 1: Pull Required Models**

```bash
ollama pull llama3.2:3b
ollama pull embeddinggemma:latest
```

**Step 2: Start Ollama Service**

```bash
ollama serve
```

>**Keep this terminal open** - Ollama needs to keep running.

**Step 3: Start Llama Stack Server**

From the **repository root directory**:

```bash
llama stack run run_llama_server.yaml
```

> **Keep this terminal open** - the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.

**Step 4: Install Agent Dependencies**

Navigate to the RAG agent directory and install dependencies:

```bash
cd agents/community/langgraph_agentic_rag
pip install -r requirements.txt
```
---

**⚡ Or with [uv](https://docs.astral.sh/uv/)** (from repo root):

1. Create venv and activate:
```bash
uv venv --python 3.12
source .venv/bin/activate
```

2. Copy shared utils into the agent package:
```bash
cp utils.py agents/community/langgraph_agentic_rag/src/langgraph_agentic_rag
```

3. Install agent (editable) and its requirements:
```bash
uv pip install -e agents/community/langgraph_agentic_rag/. -r agents/community/langgraph_agentic_rag/requirements.txt
```

4. Run the example:
```bash
uv run agents/community/langgraph_agentic_rag/examples/execute_ai_service_locally.py
```
---
**Step 5: Configure Environment Variables**

Copy the example environment file:

```bash
cp .env.example .env
```

Edit the `.env` file with your configuration:

```env
# Llama Stack Server Configuration
BASE_URL=http://localhost:8321
MODEL_ID=ollama/llama3.2:3b
API_KEY=not-needed

# RAG Configuration
VECTOR_STORE_PATH=/absolute/path/to/milvus_data/milvus_lite.db
EMBEDDING_MODEL=ollama/embeddinggemma:latest
DOCS_TO_LOAD=./data/sample_knowledge.txt

# Server Configuration
PORT=8000
```

**Important**: Update `VECTOR_STORE_PATH` to an absolute path where you want the Milvus database stored.

**Step 6: Load Documents into Vector Store**

Navigate to the data directory and run the document loader:

```bash
cd data
python load_documents.py
```

This will:
- Read documents from `sample_knowledge.txt`
- Split documents into chunks (512 characters with 128 overlap)
- Generate embeddings using the `embeddinggemma` model
- Store chunks in the Milvus Lite vector database

**Step 7: Run the Interactive Chat**

```bash
cd ../examples
python execute_ai_service_locally.py
```

You should see:
```
================================================================================
LangGraph Agentic RAG - Interactive Chat
================================================================================
Model: ollama/llama3.2:3b
Base URL: http://localhost:8321/v1
...

Choose a question or ask one of your own.
 -->
```

**Step 8: Ask Questions!**

Try asking questions about the loaded documents:
```
 --> What is LangChain?
```

## Dependencies

This agent requires the following key dependencies (see `requirements.txt` for complete list):

- `langchain-core`, `langchain-openai` - LangChain framework components
- `langgraph`, `langgraph-prebuilt` - Graph-based agent orchestration
- `llama-stack-client` - Llama Stack API client
- `fastapi`, `uvicorn` - Web service framework
- `pydantic`, `python-dotenv` - Configuration and data validation

Dependencies are installed in **Step 4** of the Quick Start guide above.

## Configuration Reference

Configuration is handled through two files:

### Llama Stack Server (`run_llama_server.yaml`)

Located in the repository root, this configures:
- Server port (8321)
- Milvus Lite vector store path
- Ollama integration URL
- Registered models (LLM and embedding)

### Application Environment (`.env`)

Environment variables (configured in Step 5 of Quick Start):

- `BASE_URL` - Llama Stack server URL (default: `http://localhost:8321`)
- `MODEL_ID` - LLM model identifier (e.g., `ollama/llama3.2:3b`)
- `API_KEY` - API authentication (use `not-needed` for local setup)
- `VECTOR_STORE_PATH` - Absolute path to Milvus Lite database file
- `EMBEDDING_MODEL` - Embedding model name (e.g., `ollama/embeddinggemma:latest`)
- `DOCS_TO_LOAD` - Path to documents for vector store (e.g., `./data/sample_knowledge.txt`)
- `PORT` - FastAPI server port (default: `8000`)

### Using with curl

```bash
# Test the health endpoint
curl http://localhost:8000/health

# Send a chat message
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is RAG?"}'
```

## Customizing Your Knowledge Base

### Using Your Own Documents

1. Create a text file with your content (e.g., `my_documents.txt`)
2. Update `.env` to point to your file:
   ```env
   DOCS_TO_LOAD=./data/my_documents.txt
   ```
3. Re-run the document loader:
   ```bash
   cd data
   python load_documents.py
   ```

### Adjusting Chunk Size

Edit `load_documents.py` to customize chunking parameters:

```python
    load_and_index_documents(
        chunk_size=512,      # Size of text chunks (default: 512)
        chunk_overlap=128,   # Overlap between chunks (default: 128)
    )
```

**Recommended chunk sizes:**
- Technical documentation: 512-1024 characters
- Narrative text: 256-512 characters
- Code snippets: 128-256 characters

# Deployment on RedHat OpenShift Cluster

### Step 1: Initialize the Agent
Navigate to the agent directory:

```bash
cd agents/community/langgraph_agentic_rag
```
Make scripts executable (first time only)

```bash
chmod +x init.sh deploy.sh   
./init.sh
```

This will:
- Load and validate environment variables from `.env` file
- Copy shared utilities (`utils.py`) to the agent source directory

### Step 2: Build image and deploy Agent
Now you need to login to OC and Docker


```bash
./deploy.sh
```

This will:
- Create Kubernetes secret for API key
- Build and push the Docker image
- Deploy the agent to OpenShift
- Create Service and Route

### Step 3: Test the Agent

Get your route URL:

```bash
oc get route langgraph-agentic-rag -o jsonpath='{.spec.host}'
```
copy the response to curl beneath to `<YOUR_ROUTE_URL>`

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is LangChain?"}'
```

## Troubleshooting

### Connection Errors

**Error**: `Connection refused to http://localhost:8321`

**Solution**: Ensure the Llama Stack server is running:
```bash
llama stack run run_llama_server.yaml
```

### No Vector Store Found

**Solution**: Load documents into the vector store:
```bash
cd data
python load_documents.py
```
There is probability that locally creadted vector store can be broken somehow. Then you need to delete insides of the `milvus_data` folder.
After that run `load_documents.py` again, and it will populate that folder.

### Empty or Irrelevant Responses

**Possible causes:**
1. **Chunk size too small** - Documents split into headers only
   - Solution: Increase `chunk_size` to 512+ in `load_documents.py`
2. **Documents not loaded** - Vector store is empty
   - Solution: Re-run `python load_documents.py`
3. **Wrong model** - Model not compatible
   - Solution: Use `llama3.2:3b` or `llama3.1:8b`


## Differences from Base Agents

This RAG agent extends the base LangGraph agent with:

1. **Retrieval Capability**: Automatic knowledge base search via Llama Stack
2. **Multi-step Workflow**: Agent → Retrieve → Generate pattern
3. **Vector Store Integration**: Milvus Lite-based document storage and retrieval
4. **Context-aware Generation**: Answers based on retrieved documents with relevance checking
5. **Llama Stack Integration**: Unified model serving and vector operations

## Additional Resources

- **[LangGraph Documentation](https://langchain-ai.github.io/langgraph/)** - LangGraph framework docs
- **[Llama Stack Documentation](https://llama-stack.readthedocs.io/)** - Llama Stack API reference
- **[Ollama Documentation](https://ollama.com/docs)** - Local model serving

## License

MIT License