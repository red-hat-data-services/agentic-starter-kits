
# Use Agent Locally

If you want to install ollama you need to install app from [Ollama site](https://ollama.com/) or via [Brew](https://formulae.brew.sh/formula/ollama#default)

```bash
#brew install ollama
# or
curl -fsSL https://ollama.com/install.sh | sh
```
---
### Setup Instructions with `pip`

**Step 1: Pull Required Models**

```bash
ollama pull llama3.2:3b
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

> **Keep this terminal open** - the server needs to keep running.\
> You should see output indicating the server started on `http://localhost:8321`.

**Step 4: Install Agent Dependencies**

Navigate to the RAG agent directory and install dependencies:

```bash
cd agents/community/langgraph_agentic_rag
pip install -r requirements.txt
```

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
```
**Step 6: Run the Interactive Chat**

```bash
cd ../examples
python execute_ai_service_locally.py
```
---
### Setup Instructions with [uv](https://docs.astral.sh/uv/)

1. Create venv and activate:
```bash
uv venv --python 3.12
source .venv/bin/activate
```

2. Copy shared utils into the agent package:
```bash
cp utils.py agents/base/langgraph_react_agent/src/langgraph_react_agent_base/
```

3. Install agent (editable) and its requirements:
```bash
uv pip install -e agents/base/langgraph_react_agent/.
uv pip install -r agents/base/langgraph_react_agent/requirements.txt
```

Edit the `.env` file and fill in all required values (see notes below):
```
API_KEY=your-api-key-here
BASE_URL=https://your-llama-stack-distribution.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/langgraph-react-agent:latest
```

**Notes:**
- `API_KEY` - contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - contact your cluster administrator
- `CONTAINER_IMAGE` - full image path where the agent container will be pushed and pulled from.
  The image is built locally, pushed to this registry, and then deployed to OpenShift.
  
  Format: `<registry>/<namespace>/<image-name>:<tag>`
  
  Examples:
  - Quay.io: `quay.io/your-username/langgraph-react-agent:latest`
  - Docker Hub: `docker.io/your-username/langgraph-react-agent:latest`
  - GHCR: `ghcr.io/your-org/langgraph-react-agent:latest`

4. Run the example:
```bash
uv run agents/base/langgraph_react_agent/examples/execute_ai_service_locally.py
```

# Deployment on RedHat OpenShift Cluster

### Step 1: Initialize the Agent
Navigate to the agent directory:

```bash
cd agents/base/langgraph_react_agent
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
oc get route langgraph-react-agent -o jsonpath='{.spec.host}'
```

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the best company? Answer with the first correct answer."}'
```

## Agent-Specific Documentation

Each agent has detailed documentation for setup and deployment:

### Base Agents

#### LangGraph ReAct Agent
- **Directory**: `agents/base/langgraph_react_agent/`
- **README**: [agents/base/langgraph_react_agent/README.md](./agents/base/langgraph_react_agent/README.md)
- **Features**: General-purpose agent with tool calling, ReAct pattern
- **Use Case**: Task automation, question answering, tool orchestration

#### LlamaIndex WebSearch Agent
- **Directory**: `agents/base/llamaindex_websearch_agent/`
- **README**: [agents/base/llamaindex_websearch_agent/README.md](./agents/base/llamaindex_websearch_agent/README.md)
- **Features**: Web search integration, workflow-based execution
- **Use Case**: Research tasks, real-time information retrieval

### Community Agents

#### LangGraph Agentic RAG
- **Directory**: `agents/community/langgraph_agentic_rag/`
- **README**: [agents/community/langgraph_agentic_rag/README.md](./agents/community/langgraph_agentic_rag/README.md)
- **Quick Start**: [agents/community/langgraph_agentic_rag/QUICKSTART.md](./agents/community/langgraph_agentic_rag/QUICKSTART.md)
- **Features**: RAG with Milvus vector store, document retrieval, context-aware generation
- **Use Case**: Document Q&A, knowledge base queries, information synthesis