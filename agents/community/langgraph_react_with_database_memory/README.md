<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.svg)

# ReACT Agent with Database Memory

</div>

---

### Preconditions:

- You need to copy/paste .env file and change its values to yours
- **Setup PostgreSQL database** for conversation persistence
- Decide what way you want to go `local` or `RH OpenShift Cluster` and fill needed values

Go to agent dir

```bash
cd agents/community/langgraph_react_with_database_memory
```

Create and activate a virtual environment (Python 3.12) in this directory using [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12
source .venv/bin/activate
```

(On Windows: `.venv\Scripts\activate`)

Copy .env file

```bash
cp ../../../template.env .env
```

#### Local

Edit the `.env` file with your local configuration:

```
# LLM Configuration
BASE_URL=http://localhost:8321/v1
MODEL_ID=ollama/llama3.2:3b
API_KEY=not-needed

# PostgreSQL Database Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
```

#### OpenShift Cluster

Edit the `.env` file and fill in all required values:

```
# LLM Configuration
API_KEY=your-api-key-here
BASE_URL=https://your-llama-stack-distribution.com/v1
MODEL_ID=llama-3.1-8b-instruct

# PostgreSQL Database Configuration
POSTGRES_HOST=your-postgres-host.com
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
```

**Notes:**

- `API_KEY` - contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - contact your cluster administrator
- `POSTGRES_HOST` - PostgreSQL database hostname
- `POSTGRES_DB` - Database name for storing conversation history
- `POSTGRES_USER` and `POSTGRES_PASSWORD` - Database credentials

---
Make scripts executable

```bash
chmod +x init.sh
```

Add values from .env to environment variables

```bash
./init.sh
```

## Local usage (Ollama + LlamaStack Server + PostgreSQL)

### Setup PostgreSQL Database

You can use Docker or a local installation:

**Option 1: Docker (Recommended for testing)**

```bash
docker run --name postgres-agent \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DB=agent_memory \
  -p 5432:5432 \
  -d postgres:16
```

**Option 2: Local PostgreSQL**

```bash
# macOS
brew install postgresql@16
brew services start postgresql@16

# adding postgresql to home path
echo 'export PATH="/usr/local/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Create database
createdb agent_memory

# check if db was created you should see "agent_memory" in 'name' column
psql -l

psql postgres -c "CREATE ROLE postgres WITH LOGIN SUPERUSER PASSWORD 'your_password_here';"
```

Create package with agent and install it to venv

```bash
uv pip install -e .
```

Install app from Ollama site or via Brew:

```bash
uv pip install ollama
```

```bash
#brew install ollama
# or
curl -fsSL https://ollama.com/install.sh | sh
```

Pull Required Model

```bash
ollama pull llama3.2:3b
```

Start Ollama Service

```bash
ollama serve
```

> **Keep this terminal open!**\
> Ollama needs to keep running.

Start LlamaStack Server

```bash
llama stack run ../../../run_llama_server.yaml
```

> **Keep this terminal open** - the server needs to keep running.\
> You should see output indicating the server started on `http://localhost:8321`.

### Run the example:

From the agent directory:

```bash
uv run python examples/execute_ai_service_locally.py
```

You should see:

```
╔════════════════════════════════════╗
║ thread_id: 123e4567-e89b-12d3-...  ║
╚════════════════════════════════════╝

[Interactive chat starts]
```

**Note the thread_id** - you can use it to continue the conversation later or delete it.

---

## Database Memory Features

### Thread-Based Conversations

This agent stores all conversation history in a PostgreSQL database using **thread IDs**:

- Each conversation is identified by a unique `thread_id`
- When you provide a `thread_id`, the agent loads previous messages from the database
- Context window is limited to the last **50 messages** (configurable in `agent.py`)
- Conversations persist across sessions - restart the agent with the same `thread_id` to continue

### Message Persistence

All messages are automatically saved to PostgreSQL:

- **Human messages** - Your input
- **AI messages** - Agent responses
- **Tool messages** - Tool execution results
- **System messages** - Prompts and instructions

The database schema is managed by LangGraph's `PostgresSaver` checkpointer:

- Tables are created automatically on first run
- No manual schema setup required

### Deleting Thread History

To permanently delete a conversation:

1. Edit `examples/clear_thread_history.py`
2. Replace the placeholder with your `thread_id`:
   ```python
   thread_id = "123e4567-e89b-12d3-a456-426614174000"
   ```
3. Run the script:
   ```bash
   python examples/clear_thread_history.py
   ```

This removes all messages for that thread from the database.

---

## OpenAI SDK for Llama-stack Connectivity

This agent uses the **OpenAI SDK** (via LangChain's `ChatOpenAI`) to connect to Llama-stack or any OpenAI-compatible
endpoint:

- **`base_url`**: Points to Llama-stack server endpoint (e.g., `http://localhost:8321/v1`)
- **`model`**: Uses Llama-stack's model identifier (e.g., `ollama/llama3.2:3b`)
- **`api_key`**: Can be "not-needed" for local Llama-stack, required for remote OpenAI

The OpenAI-compatible API allows **switching between providers** without code changes:
just update `BASE_URL`, `MODEL_ID`, and `API_KEY` in your `.env` file.

### Supported Providers:

- **Local**: Ollama via Llama-stack (`http://localhost:8321/v1`)
- **OpenAI**: OpenAI API (`https://api.openai.com/v1`)
- **Azure OpenAI**: Azure endpoints
- **vLLM**: Self-hosted vLLM servers
- **Any OpenAI-compatible API**

---

## Deployment on RedHat OpenShift Cluster

### Prerequisites

- OpenShift cluster access with `oc` CLI
- Container registry access (Quay.io, Docker Hub, etc.)
- PostgreSQL database (managed or self-hosted)

### Step 1: Configure Environment

Update your `.env` file with production values:

```bash
# LLM Configuration
BASE_URL=https://your-production-llm-endpoint.com/v1
MODEL_ID=your-production-model
API_KEY=your-production-api-key

# PostgreSQL Configuration (production database)
POSTGRES_HOST=your-production-db.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory_prod
POSTGRES_USER=produser
POSTGRES_PASSWORD=secure_password
```

### Step 2: Login to Cluster and Registry

```bash
# Login to OpenShift
oc login -u "login" -p "password" https://your-cluster:111

# Login to container registry (example: Quay.io)
docker login -u='login' -p='password' quay.io
```

### Step 3: Build and Deploy

(Note: Deployment scripts may need to be created or adapted from base agent)

```bash
# Build container
docker build -t <YOUR_CONTAINER_IMAGE> .

# Push to registry
docker push <YOUR_CONTAINER_IMAGE>

# Deploy to OpenShift (adapt deployment manifests as needed)
oc apply -f k8s/
```

### Step 4: Test Deployment

Send a test request with thread ID:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "thread_id": "test-conversation-1"
  }'
```

Continue the conversation with the same thread ID:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What did we talk about?"}],
    "thread_id": "test-conversation-1"
  }'
```

---

## Agent-Specific Documentation

### Architecture

This agent combines three key components:

1. **LangGraph ReACT Agent**: Reasoning and action loop with tool calling
2. **PostgresSaver Checkpointer**: Persistent conversation memory in PostgreSQL
3. **ChatOpenAI**: OpenAI-compatible LLM client (connects to Llama-stack or OpenAI)

```
User Input → LangGraph Agent → ChatOpenAI → LLM (Ollama/OpenAI)
                ↓                              ↓
         PostgreSQL ← PostgresSaver ← Messages & State
```

**Message Flow:**

1. User sends message with optional `thread_id`
2. Agent loads last 50 messages from PostgreSQL (if thread exists)
3. Agent processes with ReACT loop (reason → act → observe)
4. New messages saved to PostgreSQL
5. Response returned to user

### Key Differences from Base Agent

This agent extends the base LangGraph ReACT agent with:

1. **Persistent Memory**: PostgreSQL storage via `langgraph-checkpoint-postgres`
2. **Thread Management**: Unique conversation IDs for multi-session persistence
3. **Context Window**: Configurable message limit (default: 50 messages)
4. **Message Filtering**: System message prepending and history reduction
5. **Database Schema**: Auto-managed PostgreSQL tables for checkpoints and writes

### Configuration

**Environment Variables:**

| Variable            | Description        | Example                         |
|---------------------|--------------------|---------------------------------|
| `BASE_URL`          | LLM API endpoint   | `http://localhost:8321/v1`      |
| `MODEL_ID`          | Model identifier   | `ollama/llama3.2:3b`            |
| `API_KEY`           | API authentication | `not-needed` (local) or API key |
| `POSTGRES_HOST`     | Database hostname  | `localhost`                     |
| `POSTGRES_PORT`     | Database port      | `5432`                          |
| `POSTGRES_DB`       | Database name      | `agent_memory`                  |
| `POSTGRES_USER`     | Database username  | `postgres`                      |
| `POSTGRES_PASSWORD` | Database password  | (your password)                 |

**Customization:**

Edit `src/langgraph_react_with_database_memory/agent.py`:

```python
# Change context window size (default: 50 messages)
max_messages_in_context = 100  # Keep last 100 messages

# Change default system prompt
default_system_prompt = "You are a specialized assistant..."
```

### Database Schema

The PostgreSQL database contains two main tables (auto-created):

- **checkpoints**: Stores conversation state snapshots with thread IDs
- **writes**: Stores individual message writes

To inspect the database:

```bash
# Connect to PostgreSQL
docker exec -it postgres-agent psql -U postgres -d agent_memory

# List tables
\dt

# View checkpoints
SELECT thread_id, checkpoint_id FROM checkpoints;

# View message count per thread
SELECT thread_id, COUNT(*) FROM writes GROUP BY thread_id;
```

### Troubleshooting

**Error: "Environment variable `POSTGRES_HOST` is not set"**

- Solution: Ensure `.env` file exists and contains all `POSTGRES_*` variables
- Run from the agent directory where `.env` is located

**Error: "connection refused" to PostgreSQL**

- Solution: Ensure PostgreSQL is running (`docker ps` or `brew services list`)
- Check `POSTGRES_HOST` and `POSTGRES_PORT` values

**Empty responses or "I don't know"**

- Solution: The agent has no memory of previous conversations if thread_id is different
- Use the same `thread_id` to maintain conversation context

**"Too many messages" or slow responses**

- Solution: Reduce `max_messages_in_context` in `agent.py` (line 21)
- Or delete old thread history with `clear_thread_history.py`

### Additional Resources

- **LangGraph Documentation**: https://langchain-ai.github.io/langgraph/
- **LangGraph Checkpointers**: https://langchain-ai.github.io/langgraph/concepts/persistence/
- **Llama Stack Documentation**: https://llama-stack.readthedocs.io/
- **Ollama Documentation**: https://ollama.com/docs
- **PostgreSQL Documentation**: https://www.postgresql.org/docs/

---

## License

MIT License
