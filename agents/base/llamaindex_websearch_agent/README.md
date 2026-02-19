# LlamaIndex WebSearch Agent

A workflow-based AI agent built with LlamaIndex that provides web search capabilities for research tasks and real-time information retrieval.

## Features

- **Workflow-Based Architecture**: Event-driven execution using LlamaIndex Workflows
- **Web Search Tool**: Extensible web search functionality
- **FastAPI Service**: Production-ready REST API with async support
- **Dual Deployment**: Local development with LlamaStack/Ollama or production on Red Hat OpenShift
- **OpenAI-Compatible API**: Works with any OpenAI-compatible endpoint
- **Memory Management**: Built-in chat memory buffer for context retention

## Prerequisites

### For Local Development
- Python 3.11 or higher
- [Ollama](https://ollama.com/) installed
- Git

### For Red Hat OpenShift Deployment
- OpenShift CLI (`oc`) installed and authenticated
- Docker with buildx plugin (`docker buildx install`)
- `envsubst` utility (for environment variable substitution)
- Access to a container registry (Quay.io, Docker Hub, or GHCR)
- Container registry authentication (`docker login <registry>`)

---

## Part 1: Local Development with LlamaStack & Ollama

This section covers running the agent locally using LlamaStack server with Ollama for model inference.

```bash
git clone <repository-url>
cd Agentic-Starter-Kits
```
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```
If you want to install ollama you need to install app from [Ollama site](https://ollama.com/) or via [Brew](https://formulae.brew.sh/formula/ollama#default)

### Step 1: Install Ollama and Pull Models

Install Ollama if not already installed:

```bash
# macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh

# Or visit https://ollama.com/download
```

Pull the required model:

```bash
ollama pull llama3.2:3b
```

### Step 2: Start Ollama Service

```bash
ollama serve
```

>**Keep this terminal open** - Ollama needs to keep running.

### Step 3: Start Llama Stack Server

From the **repository root directory**:

```bash
llama stack run run_llama_server.yaml
```

> **Keep this terminal open** - the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.


The server will start on `http://127.0.0.1:8321` with:
- Inference API (Ollama backend)
- Vector I/O API (Milvus Lite)
- Safety API (Llama Guard)

**Configuration** (`run_llama_server.yaml`):
- Port: `8321`
- Ollama URL: `http://localhost:11434/v1`
- Model: `llama3.2:3b`

Leave this terminal running and open a new terminal for the next steps.

Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Configure Environment Variables

Create a `.env` file in the agent directory:

```bash
# Local development configuration
MODEL_ID=ollama/llama3.2:3b
BASE_URL=http://127.0.0.1:8321/v1
API_KEY=not-needed

# Comment out or remove deployment variables for local use:
#CONTAINER_IMAGE=quay.io/your-username/llamaindex-websearch-agent:latest
```

**Environment Variables Explained:**
- `MODEL_ID`: Model identifier (format: `ollama/<model-name>`)
- `BASE_URL`: LlamaStack server endpoint (must end with `/v1`)
- `API_KEY`: Not required for local Ollama (`not-needed` is a placeholder)


### Step 6: Run the Agent Locally

For a terminal-based chat interface:

```bash
python examples/execute_ai_service_locally.py
```

### Step 7: Test the Local Agent

In a new terminal, test the agent:

**Health Check:**
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "agent_initialized": true
}
```

**Send a Chat Request:**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the capital of France?"}'
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
cp utils.py agents/base/llamaindex_websearch_agent/src/llama_index_workflow_agent_base
```

3. Install agent (editable) and its requirements:
```bash
uv pip install -e agents/base/llamaindex_websearch_agent/. -r agents/base/llamaindex_websearch_agent/requirements.txt
```

4. Run the example:
```bash
uv run agents/base/llamaindex_websearch_agent/examples/execute_ai_service_locally.py
```


# Deployment to Red Hat OpenShift
w# Deployment on RedHat OpenShift Cluster

### Step 1: Initialize the Agent
Navigate to the agent directory:

```bash
cd agents/base/llamaindex_websearch_agent
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
oc get route llamaindex-websearch-agent -o jsonpath='{.spec.host}'
```
copy the response to curl beneath to `<YOUR_ROUTE_URL>`

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is LangChain?"}'
```

---

## API Reference

### POST /chat

Send a message to the agent and receive a structured response.

**Request:**
```bash
curl -X POST <AGENT_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Your question or instruction here"
  }'
```

**Response:**
```json
{
  "messages": [
    {
      "role": "user",
      "content": "Your question"
    },
    {
      "role": "assistant",
      "content": "Response text",
      "tool_calls": [
        {
          "id": "call_123",
          "type": "function",
          "function": {
            "name": "tool_name",
            "arguments": "{\"arg\":\"value\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_123",
      "name": "tool_name",
      "content": "Tool result"
    }
  ],
  "finish_reason": "stop"
}
```

### GET /health

Check agent health and initialization status.

**Request:**
```bash
curl <AGENT_URL>/health
```

**Response:**
```json
{
  "status": "healthy",
  "agent_initialized": true
}
```

---

## Available Tools

The agent includes these example tools (see `src/llama_index_workflow_agent_base/tools.py`):

### dummy_web_search

Simulates web search functionality (returns static results for demonstration).

**Parameters:**
- `query` (str): Search query string

**Example:**
```json
{
  "name": "dummy_web_search",
  "arguments": {
    "query": "latest AI news"
  }
}
```

**Returns:**
```python
["RedHat"]  # Static result for demo purposes
```

---

## Architecture

The agent uses LlamaIndex Workflows for event-driven execution:

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /chat
       ▼
┌─────────────────────┐
│  FastAPI Server     │
│   (main.py)         │
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────┐
│ FunctionCallingAgent     │
│  (LlamaIndex Workflow)   │
└────────┬─────────────────┘
         │
    ┌────┴─────────┐
    ▼              ▼
┌─────────┐   ┌─────────┐
│   LLM   │   │  Tools  │
└─────────┘   └─────────┘
```

**Workflow Steps:**

1. **prepare_chat_history**: Processes incoming messages and updates memory
2. **handle_llm_input**: Sends chat history to LLM, gets response and tool calls
3. **handle_tool_calls**: Executes tools and returns results
4. **Loop**: Repeats until no more tool calls (StopEvent)

---

## Project Structure

```
llamaindex_websearch_agent/
├── .env                          # Environment configuration (create this)
├── main.py                       # FastAPI application entry point
├── Dockerfile                    # Container image definition
├── requirements.txt              # Python dependencies
├── init.sh                       # Initialization script
├── deploy.sh                     # OpenShift deployment automation
├── src/
│   └── llama_index_workflow_agent_base/
│       ├── __init__.py
│       ├── agent.py              # Workflow closure and LLM client setup
│       ├── workflow.py           # FunctionCallingAgent workflow definition
│       ├── tools.py              # Tool implementations
│       └── utils.py              # Shared utilities (copied by init.sh)
├── k8s/
│   ├── deployment.yaml           # Kubernetes Deployment manifest
│   ├── service.yaml              # Kubernetes Service manifest
│   └── route.yaml                # OpenShift Route manifest
├── examples/
│   ├── execute_ai_service_locally.py  # Interactive chat
│   ├── ai_service.py             # AI service wrapper
│   └── _interactive_chat.py      # Chat interface
└── tests/
    └── test_tools.py             # Unit tests
```
---

## Additional Resources

- **Main Repository**: [Agentic-Starter-Kits README](../../../README.md)
- **LlamaIndex Docs**: https://docs.llamaindex.ai/
- **LlamaIndex Workflows**: https://docs.llamaindex.ai/en/stable/module_guides/workflow/
- **LlamaStack Docs**: https://llama-stack.readthedocs.io/
- **Ollama Docs**: https://docs.ollama.com/
- **OpenShift Docs**: https://docs.openshift.com/

---

## Next Steps

- **Implement Real Web Search**: Replace `dummy_web_search` with actual web search APIs (e.g., Brave Search, Tavily)
- **Add More Tools**: Integrate calculator, database queries, or external APIs
- **Enable Monitoring**: Integrate with Prometheus/Grafana
- **Add CI/CD**: Automate deployments with GitHub Actions or GitLab CI
- **Scale Horizontally**: Increase replicas for high availability
- **Implement Caching**: Add Redis for conversation history persistence
- **Streaming Responses**: Enable streaming for real-time output