<div style="text-align: center;">

![Agentic Starter Kits](/images/ask_logo.png)
# Agentic Starter Kits

</div>

## Purpose

Production-ready agent templates to build and deploy LLM-powered agents. Run locally (e.g. with Ollama/Llama Stack) or
deploy to Red Hat OpenShift. Each agent has step-by-step docs.

## Agents

Agents are organized by framework. Pick one and follow its README:

| Framework | Agent | Description |
|-----------|-------|-------------|
| **LangGraph** | [ReAct Agent](./agents/langgraph/react_agent/) | General-purpose agent using a ReAct loop: it reasons and calls tools (e.g. search, math) step by step. Built with LangGraph and LangChain. |
| **LangGraph** | [Agentic RAG](./agents/langgraph/agentic_rag/) | RAG agent that indexes documents in a vector store (Milvus) and retrieves relevant chunks to augment the LLM's answers with your own data. |
| **LangGraph** | [ReAct + DB Memory](./agents/langgraph/react_with_database_memory/) | ReAct agent with PostgreSQL-backed conversation memory. Full chat history is persisted in the database while a FIFO sliding window keeps only the last N messages in the LLM context. |
| **LlamaIndex** | [WebSearch Agent](./agents/llamaindex/websearch_agent/) | Agent built on LlamaIndex that uses a web search tool to query the internet and use the results in its answers. |
| **CrewAI** | [WebSearch Agent](./agents/crewai/websearch_agent/) | CrewAI-based agent with a web search tool to query the internet and answer user questions. |
| **Vanilla Python** | [OpenAI Responses Agent](./agents/vanilla_python/openai_responses_agent/) | Minimal agent with no framework: only the OpenAI Python client and an Action/Observation loop with tools. Use with OpenAI or any compatible API. |
| **AutoGen** | [MCP Agent](./agents/autogen/mcp_agent/) | AutoGen AssistantAgent with MCP tools over SSE (e.g. churn prediction, math tools), FastAPI `/chat/completions`. |
| **Langflow** | [Simple Tool Calling Agent](./agents/langflow/simple_tool_calling_agent/) | Outdoor activity planner built with Langflow's visual UI. Uses weather, air quality, and NPS APIs. Runs via `podman-compose` (see its own README). |

## Deployment Options

Agents in this repository support two deployment modes:

### 🖥️ Local Development

- Run agents on your local machine
- Use Llama Stack server with Ollama for model serving
- Ideal for development, testing, and experimentation
- No cloud infrastructure required

```bash
git clone https://github.com/red-hat-data-services/agentic-starter-kits
cd agentic-starter-kits

# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Pick an agent and go
cd agents/langgraph/react_agent
make init        # creates .env from .env.example
# Edit .env with your API_KEY, BASE_URL, MODEL_ID
make run         # starts on http://localhost:8080
```

See [Local Development Guide](./docs/local-development.md) for Ollama + Llama Stack setup.

### ☁️ Production Deployment

- Deploy agents to Red Hat OpenShift Cluster
- Containerized deployment with Kubernetes
- Production-grade scaling and monitoring
- CI/CD ready

```bash
cd agents/langgraph/react_agent

# Option A: Build locally with Podman (or Docker) and push to a registry
make build            # builds container image locally
make push             # pushes image to registry
make deploy           # deploys via Helm

# Option B: Build in-cluster on OpenShift (no Podman/Docker needed)
make build-openshift  # builds image via OpenShift BuildConfig
make deploy           # deploys via Helm
```

Preview rendered Helm manifests before deploying:

```bash
make dry-run
```

See [OpenShift Deployment Guide](./docs/openshift-deployment.md) for details.

## Repository Structure

```
agentic-starter-kits/
├── agents/
│   ├── langgraph/
│   │   ├── react_agent/              # LangGraph ReAct agent
│   │   ├── agentic_rag/             # LangGraph RAG agent with Milvus
│   │   └── react_with_database_memory/ # LangGraph ReAct + PostgreSQL memory
│   ├── crewai/
│   │   └── websearch_agent/         # CrewAI web search agent
│   ├── llamaindex/
│   │   └── websearch_agent/         # LlamaIndex web search agent
│   ├── vanilla_python/
│   │   └── openai_responses_agent/  # OpenAI Responses API (no framework)
│   ├── autogen/
│   │   └── mcp_agent/               # AutoGen + MCP (SSE)
│   └── langflow/
│       └── simple_tool_calling_agent/ # Langflow visual agent (podman-compose)
├── charts/
│   └── agent/                       # Shared Helm chart for all agents
├── docs/                            # Guides: deployment, local dev, contributing
├── infrastructure/
│   └── llama-stack/                 # Llama Stack server configuration
└── README.md
```

Each Helm-based agent directory contains:

```
agent-name/
├── agent.yaml         # Agent metadata and required env vars
├── values.yaml        # Helm values override for this agent
├── .env.example       # Environment variable template
├── Makefile           # make init, run, build, build-openshift, deploy, dry-run, test
├── Dockerfile         # Container build
├── pyproject.toml     # Python dependencies
├── main.py            # FastAPI app (/chat/completions, /health)
├── src/               # Agent source code
├── tests/             # Tests
└── examples/          # Example scripts
```

## Documentation

- [Local Development](./docs/local-development.md) — Ollama + Llama Stack setup
- [OpenShift Deployment](./docs/openshift-deployment.md) — Helm-based deployment guide
- [Adding a New Agent](./docs/adding-a-new-agent.md) — How to contribute a new agent template

## Additional Resources

- **Llama Stack**: https://llama-stack.readthedocs.io/
- **Ollama**: https://docs.ollama.com/
- **Red Hat OpenShift**: https://docs.openshift.com/
- **Helm**: https://helm.sh/docs/
- **Kubernetes**: https://kubernetes.io/docs/

## Contributing

Contributions are welcome! See [Adding a New Agent](./docs/adding-a-new-agent.md) and [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[Apache License 2.0](./LICENSE)
