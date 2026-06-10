# Langflow Agents

Agent templates built with [Langflow](https://docs.langflow.org/)'s visual flow builder.

> **Note:** Langflow agents are different from other agents in this repo. They do not deploy a custom container — the "agent" is a JSON flow definition imported into an existing Langflow instance. See each agent's README for details.

## Available Agents

| Agent | Description |
|-------|-------------|
| [Simple Tool Calling Agent](templates/simple_tool_calling_agent/) | Tool-calling agent that calls external APIs (weather, parks) and reasons over results. Includes Langfuse v3 tracing. |
