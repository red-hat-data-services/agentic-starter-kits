# OpenAI Responses Agent

Agent **without any agentic framework**: uses only the **OpenAI Python client** and **pure Python** (Responses API). No LlamaStack, LangChain, LlamaIndex, etc. – to show it can be done without frameworks. Uses `AIAgent` with chat, tools, and Action/Observation loop. Compatible with OpenAI API or any OpenAI-compatible endpoint (e.g. `BASE_URL` override). Python 3.12+.

# Use Agent Locally

### Installation

```bash
git clone <repository-url>
cd Agentic-Starter-Kits
```
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

If you want to install Ollama: [Ollama site](https://ollama.com/) or [Brew](https://formulae.brew.sh/formula/ollama#default).

**Install agent dependencies** (OpenAI client):

```bash
cd agents/base/openai_responses_agent
uv pip install -e .
# or: poetry install
```

### Setup Instructions

**Option A – OpenAI API**

Create `.env` in the agent directory (or use repo `template.env`):

```env
BASE_URL=https://api.openai.com/v1
MODEL_ID=gpt-4o-mini
API_KEY=sk-...
```

**Option B – Local OpenAI-compatible endpoint (e.g. Ollama)**

1. Pull model and run Ollama (or another OpenAI-compatible server).
2. In `.env` set e.g. `BASE_URL=http://localhost:11434/v1`, `MODEL_ID=llama3.2`, `API_KEY=not-needed` (if not required).

**Configure Environment Variables**

Copy the template (from repo root: `template.env`) or create `.env` in the agent directory:

```bash
cp ../../../template.env .env
```

Edit `.env` with `BASE_URL`, `MODEL_ID`, and `API_KEY` as above.

**Run the example**

```bash
cd examples
python execute_ai_service_locally.py
```

**⚡ Or with [uv](https://docs.astral.sh/uv/)** (from repo root):

1. Create venv and activate:
```bash
uv venv --python 3.12
source .venv/bin/activate
```

2. Copy shared utils into the agent package:
```bash
cp utils.py agents/base/openai_responses_agent/src/openai_responses_agent_base/
```

3. Install agent (editable) and its requirements:
```bash
uv pip install -e agents/base/openai_responses_agent/. -r agents/base/openai_responses_agent/requirements.txt
```

4. Run the example:
```bash
uv run agents/base/openai_responses_agent/examples/execute_ai_service_locally.py
```

# Deployment on Red Hat OpenShift Cluster

### Step 1: Initialize the Agent

```bash
cd agents/base/openai_responses_agent
chmod +x init.sh deploy.sh
./init.sh
```

This loads `.env`, validates variables, and copies `utils.py` into the agent package.

### Step 2: Build Image and Deploy

```bash
./deploy.sh
```

This creates the API key secret, builds and pushes the image, and deploys the agent (Deployment, Service, Route).

### Step 3: Test the Agent

Get the route host:

```bash
oc get route openai-responses-agent -o jsonpath='{.spec.host}'
```

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How much does a Lenovo Laptop costs and what are the reviews?"}'
```

## References

- [OpenAI Python client](https://github.com/openai/openai-python) and [Responses API](https://platform.openai.com/docs/api-reference/responses/create)
