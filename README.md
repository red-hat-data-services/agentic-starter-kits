<div style="text-align: center;">

![Agentic Starter Kits](/images/ask_logo.png)

# Agentic Starter Kits

</div>

## Purpose

Production-ready starter kits for building and deploying AI agents on Red Hat OpenShift. Each kit is self-contained with docs and deployment configs - most include a Makefile, Dockerfile, and Helm chart. Build locally, then deploy to OpenShift without stitching together boilerplate.

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
| **Google ADK** | [ADK Agent](./agents/google/templates/adk/) | General-purpose agent using Google ADK 2.0 with LiteLLM to route inference through an OGX-compatible endpoint. |
| **Langflow** | [Simple Tool Calling Agent](./agents/langflow/templates/simple_tool_calling_agent/) | Tool-calling agent built with Langflow's visual flow builder. Calls external APIs as tools and reasons over results. Includes Langfuse v3 tracing. Runs locally via `podman-compose`. |
| **A2A** | [LangGraph + CrewAI Agent](./agents/a2a/templates/langgraph_crewai_agent/) | Multi-agent system using the Agent-to-Agent (A2A) protocol. A LangGraph orchestrator delegates tasks to a CrewAI worker agent. Uses a dedicated Helm chart. |
| **Claude Code** | [Claude Code on OpenShift](./agents/claude-code/) | Deploy Claude Code on OpenShift with multiple backend options (Anthropic API, Vertex AI, vLLM, OGX). Includes deployment manifests and configuration guides. |
| **OpenClaw** | [OpenClaw on OpenShift](./agents/openclaw/deployment/) | Deploy OpenClaw on OpenShift with vLLM model serving, OAuth SSO, and production-grade security. Kustomize-based deployment using pre-built images. |
| **Codex** | [Codex on OpenShift](./agents/codex/deployment/) | Run OpenAI Codex CLI inside an OpenShell sandbox on OpenShift. Containerfile-based deployment. |
| **OpenCode** | [OpenCode on OpenShift](./agents/opencode/deployment/) | Run OpenCode inside an OpenShell sandbox on OpenShift. Containerfile-based deployment. |

## Getting Started

```bash
git clone https://github.com/red-hat-data-services/agentic-starter-kits
cd agentic-starter-kits
```

Install [uv](https://docs.astral.sh/uv/) (Python package manager):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Pick an agent from the table above, `cd` into its directory, and follow its README for setup, local development, and deployment to OpenShift.

- **Local development** — run agents on your machine with Ollama or OGX for model serving. See the [Local Development](./docs/local-development.md) guide.
- **Production deployment** — containerized deployment on Red Hat OpenShift with Helm charts, monitoring, and production-grade scaling. See the [OpenShift Deployment](./docs/openshift-deployment.md) guide.

## Repository Structure

```text
agentic-starter-kits/
├── agents/
│   ├── langgraph/                       # Each framework follows this layout
│   │   ├── templates/                   # Agent templates
│   │   │   ├── react_agent/
│   │   │   ├── agentic_rag/
│   │   │   ├── react_with_database_memory/
│   │   │   └── human_in_the_loop/
│   │   ├── examples/                    # Business use-case demos
│   │   └── deployment/                  # Helm chart for this framework
│   ├── crewai/
│   ├── llamaindex/
│   ├── vanilla_python/
│   ├── autogen/
│   ├── google/
│   ├── langflow/
│   ├── claude-code/
│   ├── openclaw/
│   ├── codex/
│   ├── opencode/
│   └── a2a/
├── components/                          # Shared reusable packages (auth, etc.)
├── evals/
│   ├── harness/                         # Shared eval engine (runner, scorers, MLflow client)
│   └── evalhub_adapter/                 # EvalHub on-cluster adapter (JobSpec → harness)
├── tests/
│   └── behavioral/                      # Behavioral eval suite
├── sandboxes/
│   └── base/                            # OpenShell base container image
├── infrastructure/
│   └── llm-d/                           # llm-d deployment manifests and test tooling
├── docs/                                # Guides: local dev, deployment, contributing
├── pyproject.toml                       # Test deps & pytest config
└── README.md
```

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
| `LANGFLOW_TOOL_CALLING_AGENT_URL` | Langflow Simple Tool Calling agent tests |
| `LANGFLOW_FLOW_ID` | Langflow flow ID (changes on re-import) |
| `HITL_AGENT_URL` | LangGraph Human-in-the-Loop agent tests |
| `GOOGLE_ADK_AGENT_URL` | Google ADK agent tests |
| `A2A_LANGGRAPH_CREWAI_AGENT_URL` | A2A LangGraph-CrewAI agent tests |

```bash
uv pip install -e ".[test]"
AGENT_URL=https://my-agent.example.com pytest tests/behavioral/ -v
```

See `tests/behavioral/` for full details.

## Documentation

- [Local Development](./docs/local-development.md) — Ollama + OGX setup
- [OpenShift Deployment](./docs/openshift-deployment.md) — Helm-based deployment guide
- [Adding a New Agent](./docs/adding-a-new-agent.md) — How to contribute a new agent template
- [Adding Behavioral Tests](./docs/adding-behavioral-tests.md) — How to add test coverage for an agent
- [Adding an EvalHub Agent Integration](./docs/adding-evalhub-agent-integration.md) — How to integrate a new agent into the EvalHub evaluation pipeline
- [llm-d Deployment](./docs/llm-d-deployment.md) — Deploy llm-d for intelligent LLM inference routing on OpenShift AI

## Claude Code Skills

This project has [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills that automate contributor workflows — tracing integration, deployment, test scaffolding, and more. Contributor and operator skills are in the [agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills) plugin. See [CONTRIBUTING.md — Claude Code skills](CONTRIBUTING.md#claude-code-skills) for installation instructions and the full skill list.

## Additional Resources

- **OGX Documentation**: <https://ogx-ai.github.io/docs/>
- **Ollama Documentation**: <https://docs.ollama.com/>
- **OpenShift Documentation**: <https://docs.openshift.com/>
- **Kubernetes**: <https://kubernetes.io/docs/>

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[Apache License 2.0](LICENSE)
