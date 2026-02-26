<div style="text-align: center;">

![Agentic Starter Kits](/images/ask_logo.png)

# Agentic Starter Kits

</div>

## Purpose

Agentic Starter Kits is a collection of production-ready agent templates that demonstrate how to build and deploy
LLM-powered agents using modern frameworks. This repository provides:

- **Base Agent Templates**: Ready-to-use agent implementations using LangGraph and LlamaIndex
- **Community Agent Examples**: Advanced agents like RAG (Retrieval-Augmented Generation) systems
- **Dual Deployment Options**: Run agents locally for development or deploy to Red Hat OpenShift Cluster for production
- **Llama stack Integration**: Unified model serving with Ollama for local LLM inference
- **Clear Documentation**: Step-by-step guides for setup, configuration, and deployment

## Deployment Options

Agents in this repository can support two deployment modes:

### 🖥️ Local Development

- Run agents on your local machine
- Use Llama Stack server with Ollama for model serving
- Ideal for development, testing, and experimentation
- No cloud infrastructure required

### ☁️ Production Deployment

- Deploy agents to Red Hat OpenShift Cluster
- Containerized deployment with Kubernetes
- Production-grade scaling and monitoring
- CI/CD ready

## Repository Structure

```
Agentic-Starter-Kits/
├── agents/
│   ├── base/
│   │   ├── langgraph_react_agent/       # LangGraph ReAct agent 
│   │   └── llamaindex_websearch_agent/  # LlamaIndex web search agent
│   │   └── openai_responses_agent/      # OpenAI Responses API (no framework)
│   └── community/
│       └── langgraph_agentic_rag/       # RAG agent with Milvus vector store
├── run_llama_server.yaml                # Llama Stack server configuration
├── utils.py                             # Shared utilities
└── README.md                            # This file
```

---

## How to Use This Repository

1. **Start Here**: Read this README to understand the overall structure and install core dependencies
2. **Choose an Agent**: Select an agent from the `agents/` directory based on your use case
3. **Follow Agent README**: Navigate to the agent's directory and follow its specific README for:
    - Agent-specific dependencies installation
    - Configuration and setup
    - Local development or OpenShift deployment
    - Usage examples and API endpoints

### Pre-requisitions to run that repo

Run this script to set up repo stuff with a use of [UV](https://docs.astral.sh/uv/) and python 3.12

Download repo

```bash
git clone https://github.com/red-hat-data-services/agentic-starter-kits
```

Get into root dir

```bash
cd agentic-starter-kits
```

Install UV

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Next Steps

After completing the setup, choose an agent and follow its specific README:

**Base Agents:**

- **[LangGraph ReAct Agent](./agents/base/langgraph_react_agent/README.md)** - General-purpose agent with tool use
- **[LlamaIndex WebSearch Agent](./agents/base/llamaindex_websearch_agent/README.md)** - Web search capabilities
- **[OpenAI Responses Agent](./agents/base/openai_responses_agent/README.md)** - OpenAI client + pure Python (Responses
  API)

**Community Agents:**

- **[LangGraph Agentic RAG](./agents/community/langgraph_agentic_rag/README.md)** - RAG with Milvus vector store
- **[LangGraph ReACT Agent with PostgresSQL](./agents/community/langgraph_agentic_rag/README.md)** - RAG with Milvus
  vector store

## Additional Resources

- **Llama Stack Documentation**: https://llama-stack.readthedocs.io/
- **Ollama Documentation**: https://docs.ollama.com/
- **OpenShift Documentation**: https://docs.openshift.com/
- **Kubernetes**: https://kubernetes.io/docs/

## Contributing

Contributions are welcome! Please see individual agent READMEs for specific guidelines.

## License

MIT License