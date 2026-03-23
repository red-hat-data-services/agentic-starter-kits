<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# ReAct Agent with Database Memory

</div>

---

## What this agent does

ReAct agent with PostgreSQL-backed conversation memory for persistent, thread-based chat history.
Uses OpenAI-compatible APIs for LLM access and LangGraph's `PostgresSaver` checkpointer for persistence.
Built with LangGraph and LangChain.

---

## Quick Start

```bash
cd agents/langgraph/react_with_database_memory
make init        # creates .env from .env.example
# Edit .env with your API_KEY, BASE_URL, MODEL_ID, POSTGRES_* vars
make run         # starts on http://localhost:8080
```

## Prerequisites

A PostgreSQL database is required.

**Option 1: Docker**

```bash
docker run --name postgres-agent \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DB=agent_memory \
  -p 5432:5432 \
  -d postgres:16
```

**Option 2: Local PostgreSQL (macOS)**

```bash
brew install postgresql@16
brew services start postgresql@16
createdb agent_memory
psql postgres -c "CREATE ROLE postgres WITH LOGIN SUPERUSER PASSWORD 'mypassword';"
```

## Configuration

### Local

```
API_KEY=not-needed
BASE_URL=http://localhost:8321/v1
MODEL_ID=ollama/llama3.2:3b
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=postgres
POSTGRES_PASSWORD=mypassword
```

See [Local Development](../../../docs/local-development.md) for Ollama + Llama Stack setup.

### OpenShift / Remote API

```
API_KEY=your-api-key-here
BASE_URL=https://your-model-endpoint.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/langgraph-react-db-memory:latest
POSTGRES_HOST=your-postgres-host.com
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=produser
POSTGRES_PASSWORD=secure_password
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/langgraph-react-db-memory:latest`
    - Docker Hub: `docker.io/your-username/langgraph-react-db-memory:latest`
    - GHCR: `ghcr.io/your-org/langgraph-react-db-memory:latest`

- `POSTGRES_HOST` - PostgreSQL database hostname
- `POSTGRES_DB` - Database name for storing conversation history
- `POSTGRES_USER` and `POSTGRES_PASSWORD` - Database credentials

## Deploying to OpenShift

```bash
# Option A: Build locally with Podman (or Docker) and push to a registry
make build            # builds container image locally
make push             # pushes image to registry
make deploy           # deploys via Helm

# Option B: Build in-cluster on OpenShift (no Podman/Docker needed)
make build-openshift  # builds image via OpenShift BuildConfig
make deploy

# Preview rendered manifests before deploying
make dry-run
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for details.

### Testing on OpenShift

Get the route URL:

```bash
oc get route langgraph-react-db-memory -o jsonpath='{.spec.host}'
```

Replace `http://localhost:8080` with `https://<YOUR_ROUTE_URL>` in the API examples below.

## API Endpoints

### POST /chat/completions

Non-streaming:

```bash
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "I will tell you a story about blue eyed Johnny! He liked ice creams. End."}],
    "stream": false,
    "thread_id": "test-conversation-1"
  }'
```

Continue the conversation with the same `thread_id`:

```bash
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What did we talk about?"}],
    "stream": false,
    "thread_id": "test-conversation-1"
  }'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What did we talk about?"}],
    "stream": true,
    "thread_id": "test-conversation-1"
  }'
```

Pretty Printed Stream:

```bash
curl -sN -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What did we talk about?"}],
    "stream": true,
    "thread_id": "test-conversation-1"
  }' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

## Playground UI

A browser-based chat interface is served directly by the agent at the root URL — no separate process needed.

### Running the Playground

Start the agent and open the root URL in your browser:

```bash
uvicorn main:app --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

A green dot in the header means the agent is connected and ready. Each browser session gets a unique thread ID displayed in the header — conversation history persists in the database via that thread.

When deployed to OpenShift, the playground is available at the route URL.

### Standalone Flask Playground (alternative)

You can also run the playground as a separate Flask app if needed:

```bash
uv pip install flask
```

```bash
# Terminal 1: Start the agent
uvicorn main:app --port 8000

# Terminal 2: Start the playground
flask --app playground/app run --port 5001
```

| Variable    | Default                  | Description                     |
|-------------|--------------------------|---------------------------------|
| `AGENT_URL` | `http://localhost:8000`  | URL of the running agent API    |

If the agent runs on a different host or port:

```bash
AGENT_URL=https://your-agent-url flask --app playground/app run --port 5001
```

### GET /health

```bash
curl http://localhost:8080/health
```

## Architecture

This agent combines three key components:

1. **LangGraph ReAct Agent** — reasoning and action loop with tool calling
2. **PostgresSaver Checkpointer** — persistent conversation memory in PostgreSQL
3. **ChatOpenAI** — OpenAI-compatible LLM client (connects to Llama Stack, OpenAI, vLLM, or any compatible API)

```
User Input → LangGraph Agent → ChatOpenAI → LLM (Ollama/OpenAI)
                ↓                              ↓
         PostgreSQL ← PostgresSaver ← Messages & State
```

**Message Flow:**

1. User sends message with optional `thread_id`
2. Agent loads previous messages from PostgreSQL (if thread exists)
3. Agent processes with ReAct loop (reason → act → observe)
4. New messages saved to PostgreSQL
5. Response returned to user

## Database Memory Features

### Thread-Based Conversations

This agent stores all conversation history in a PostgreSQL database using **thread IDs**:

- Each conversation is identified by a unique `thread_id`
- When you provide a `thread_id`, the agent loads previous messages from the database
- Context window is limited to the last **5 messages** (configurable in `agent.py`)
- Conversations persist across sessions — restart the agent with the same `thread_id` to continue

### Message Persistence

All messages are automatically saved to PostgreSQL:

- **Human messages** — your input
- **AI messages** — agent responses
- **Tool messages** — tool execution results
- **System messages** — prompts and instructions

The database schema is managed by LangGraph's `PostgresSaver` checkpointer:

- **checkpoints** table — stores conversation state snapshots with thread IDs
- **writes** table — stores individual message writes
- Tables are created automatically on first run — no manual schema setup required

### Customization

Edit `src/react_with_database_memory/agent.py`:

```python
# Change context window size (default: 5 messages)
max_messages_in_context = 10

# Change default system prompt
default_system_prompt = "You are a specialized assistant..."
```

### Deleting Thread History

To permanently delete a conversation thread:

1. Edit `examples/clear_thread_history.py` and set your `thread_id`
2. Run:
   ```bash
   uv run python examples/clear_thread_history.py
   ```

### Inspecting the Database

```bash
docker exec -it postgres-agent psql -U postgres -d agent_memory

# List tables
\dt

# View checkpoints
SELECT thread_id, checkpoint_id FROM checkpoints;

# View message count per thread
SELECT thread_id, COUNT(*) FROM writes GROUP BY thread_id;
```

## Troubleshooting

- **"Environment variable `POSTGRES_HOST` is not set"** — Ensure `.env` file exists and contains all `POSTGRES_*` variables. Run from the agent directory where `.env` is located.
- **"connection refused" to PostgreSQL** — Ensure PostgreSQL is running (`docker ps` or `brew services list`). Check `POSTGRES_HOST` and `POSTGRES_PORT` values.
- **Empty responses or "I don't know"** — The agent has no memory of previous conversations if `thread_id` is different. Use the same `thread_id` to maintain context.
- **Slow responses** — Reduce `max_messages_in_context` in `agent.py` or delete old thread history.

## Tests

```bash
make test
```

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph Checkpointers](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangChain Documentation](https://python.langchain.com/)
- [Llama Stack Documentation](https://llama-stack.readthedocs.io/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
