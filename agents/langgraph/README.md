# LangGraph Agents

Agent templates built with [LangGraph](https://langchain-ai.github.io/langgraph/) and [LangChain](https://www.langchain.com/).

## Available Agents

| Agent | Description |
|-------|-------------|
| [react_agent](templates/react_agent/) | General-purpose ReAct loop agent that reasons and calls tools step by step |
| [agentic_rag](templates/agentic_rag/) | RAG agent that indexes documents in Milvus and retrieves relevant chunks to augment answers |
| [react_with_database_memory](templates/react_with_database_memory/) | ReAct agent with PostgreSQL-backed conversation memory for persistent, thread-based chat history |
| [human_in_the_loop](templates/human_in_the_loop/) | Agent with Human-in-the-Loop approval that pauses for human review before executing sensitive tools (e.g. send_email) |

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Documentation](https://python.langchain.com/)
