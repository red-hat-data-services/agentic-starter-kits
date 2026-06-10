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
| **LangGraph** | [ReAct Agent](./agents/langgraph/templates/react_agent/) | General-purpose agent using a ReAct loop: it reasons and calls tools (e.g. search, math) step by step. Built with LangGraph and LangChain. |
| **LangGraph** | [Agentic RAG](./agents/langgraph/templates/agentic_rag/) | RAG agent that indexes documents in a vector store (Milvus) and retrieves relevant chunks to augment the LLM's answers with your own data. |
| **LangGraph** | [ReAct + DB Memory](./agents/langgraph/templates/react_with_database_memory/) | ReAct agent with PostgreSQL-backed conversation memory. Full chat history is persisted in the database while a FIFO sliding window keeps only the last N messages in the LLM context. |
| **LangGraph** | [Human-in-the-Loop](./agents/langgraph/templates/human_in_the_loop/) | ReAct agent with a human approval step. The agent pauses before executing tool calls and waits for user confirmation, enabling oversight of critical actions. |
| **LlamaIndex** | [WebSearch Agent](./agents/llamaindex/templates/websearch_agent/) | Agent built on LlamaIndex that uses a web search tool to query the internet and use the results in its answers. |
| **CrewAI** | [WebSearch Agent](./agents/crewai/templates/websearch_agent/) | CrewAI-based agent with a web search tool to query the internet and answer user questions. |
| **Vanilla Python** | [OpenAI Responses Agent](./agents/vanilla_python/templates/openai_responses_agent/) | Minimal agent with no framework: only the OpenAI Python client and an Action/Observation loop with tools. Use with OpenAI or any compatible API. |
| **AutoGen** | [MCP Agent](./agents/autogen/templates/mcp_agent/) | AutoGen AssistantAgent with MCP tools over SSE (e.g. churn prediction, math tools), FastAPI `/chat/completions`. |
| **Google ADK** | [ADK Agent](./agents/google/templates/adk/) | General-purpose agent using Google ADK 2.0 with LiteLLM to route inference through a LlamaStack-compatible endpoint. |
| **Langflow** | [Simple Tool Calling Agent](./agents/langflow/templates/simple_tool_calling_agent/) | Tool-calling agent built with Langflow's visual flow builder. Calls external APIs as tools and reasons over results. Includes Langfuse v3 tracing. Runs locally via `podman-compose`. |
| **A2A** | [LangGraph + CrewAI Agent](./agents/a2a/templates/langgraph_crewai_agent/) | Multi-agent system using the Agent-to-Agent (A2A) protocol. A LangGraph orchestrator delegates tasks to a CrewAI worker agent. Uses a dedicated Helm chart. |

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

```text
agentic-starter-kits/
├── agents/
│   ├── langgraph/
│   │   ├── templates/
│   │   │   ├── react_agent/              # LangGraph ReAct agent
│   │   │   ├── agentic_rag/             # LangGraph RAG agent with Milvus
│   │   │   ├── react_with_database_memory/ # LangGraph ReAct + PostgreSQL memory
│   │   │   └── human_in_the_loop/       # LangGraph Human-in-the-Loop agent
│   │   └── examples/                    # Business use-case demos
│   ├── crewai/
│   │   ├── templates/
│   │   │   └── websearch_agent/         # CrewAI web search agent
│   │   └── examples/
│   ├── llamaindex/
│   │   ├── templates/
│   │   │   └── websearch_agent/         # LlamaIndex web search agent
│   │   └── examples/
│   ├── vanilla_python/
│   │   ├── templates/
│   │   │   └── openai_responses_agent/  # OpenAI Responses API (no framework)
│   │   └── examples/
│   ├── autogen/
│   │   ├── templates/
│   │   │   └── mcp_agent/               # AutoGen + MCP (SSE)
│   │   └── examples/
│   ├── google/
│   │   ├── templates/
│   │   │   └── adk/                     # Google ADK 2.0 agent
│   │   └── examples/
│   ├── langflow/
│   │   ├── templates/
│   │   │   └── simple_tool_calling_agent/ # Langflow tool-calling agent
│   │   └── examples/
│   └── a2a/
│       ├── templates/
│       │   └── langgraph_crewai_agent/  # A2A multi-agent (LangGraph + CrewAI)
│       └── examples/
├── evals/
│   ├── harness/                     # Shared eval engine (runner, scorers, MLflow client)
│   └── evalhub_adapter/             # EvalHub on-cluster adapter (JobSpec → harness)
├── tests/
│   └── behavioral/                  # Behavioral eval suite (shared infra)
├── charts/
│   ├── agent/                       # Shared Helm chart for all standard agents
│   └── a2a-langgraph-crewai/        # Dedicated Helm chart for A2A agent
├── infrastructure/
│   └── llm-d/                       # llm-d deployment manifests and test tooling
├── docs/                            # Guides: local dev, deployment, contributing
├── pyproject.toml                   # Test deps & pytest config
└── README.md
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

## Behavioral Tests

Behavioral eval suite that tests agents over HTTP against their shared OpenAI-compatible API. Tests are organized by capability so they apply to any agent.

Tests require a running agent. Set the target URL via environment variables:

| Env var | Test scope |
|---------|------------|
| `AGENT_URL` | Cross-agent tests (api_contract, adversarial) |
| `REACT_AGENT_URL` | LangGraph ReAct agent tests |
| `VANILLA_PYTHON_AGENT_URL` | Vanilla Python agent tests |
| `AUTOGEN_MCP_AGENT_URL` | AutoGen MCP agent tests |
| `CREWAI_WEBSEARCH_AGENT_URL` | CrewAI Websearch agent tests |
| `AGENTIC_RAG_AGENT_URL` | LangGraph Agentic RAG agent tests |
| `DB_MEMORY_AGENT_URL` | LangGraph DB Memory agent tests |
| `LLAMAINDEX_WEBSEARCH_AGENT_URL` | LlamaIndex Websearch agent tests |
| `LANGFLOW_AGENT_URL` | Langflow Simple Tool Calling agent tests |
| `LANGFLOW_FLOW_ID` | Langflow flow ID (changes on re-import) |
| `HITL_AGENT_URL` | LangGraph Human-in-the-Loop agent tests |

```bash
uv pip install -e ".[test]"
AGENT_URL=https://my-agent.example.com pytest tests/behavioral/ -v
```

See `tests/behavioral/` for full details.

---

## Documentation

- [Local Development](./docs/local-development.md) — Ollama + Llama Stack setup
- [OpenShift Deployment](./docs/openshift-deployment.md) — Helm-based deployment guide
- [Adding a New Agent](./docs/adding-a-new-agent.md) — How to contribute a new agent template
- [Adding Behavioral Tests](./docs/adding-behavioral-tests.md) — How to add test coverage for an agent
- [Adding an EvalHub Agent Integration](./docs/adding-evalhub-agent-integration.md) — How to integrate a new agent into the EvalHub evaluation pipeline
- [llm-d Deployment](./docs/llm-d-deployment.md) — Deploy llm-d for intelligent LLM inference routing on OpenShift AI

## Additional Resources

- **Llama Stack Documentation**: <https://llama-stack.readthedocs.io/>
- **Ollama Documentation**: <https://docs.ollama.com/>
- **OpenShift Documentation**: <https://docs.openshift.com/>
- **Kubernetes**: <https://kubernetes.io/docs/>

## Contributing

Contributions are welcome! Please see individual agent READMEs for specific guidelines.

## License

MIT License

Copyright (c) 2026
