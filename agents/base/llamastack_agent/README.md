# LlamaStack Agent

Agent built **only on the LlamaStack API** ([llama-stack-client](https://pypi.org/project/llama-stack-client/)), without LlamaIndex. Uses `AIAgent` with chat, tools, and Action/Observation loop. Python 3.12+ required.

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

**Install Llama Stack**:

```bash
pip install llama-stack llama-stack-client
```

### Setup Instructions

**Step 1: Pull Required Models**

```bash
ollama pull llama3.2:3b
```

**Step 2: Start Ollama Service**

```bash
ollama serve
```

> **Keep this terminal open** – Ollama needs to keep running.

**Step 3: Start Llama Stack Server**

From the **repository root directory**:

```bash
llama stack run run_llama_server.yaml
```

> **Keep this terminal open** – server runs at `http://localhost:8321`.

**Step 4: Install Agent Dependencies**

```bash
cd agents/base/llamastack_agent
pip install -r requirements.txt
```

**Step 5: Configure Environment Variables**

Copy the template (from repo root: `template.env`) or create `.env` in the agent directory:

```bash
cp ../../../template.env .env
```

Edit `.env`:

```env
BASE_URL=http://localhost:8321
MODEL_ID=ollama/llama3.2:3b
API_KEY=not-needed
```

**Step 6: Run the Interactive Chat**

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
cp utils.py agents/base/llamastack_agent/src/llamastack_agent_base/
```

3. Install agent (editable) and its requirements:
```bash
uv pip install -e agents/base/llamastack_agent/. -r agents/base/llamastack_agent/requirements.txt
```

4. Run the example:
```bash
uv run agents/base/llamastack_agent/examples/execute_ai_service_locally.py
```

# Deployment on Red Hat OpenShift Cluster

### Step 1: Initialize the Agent

```bash
cd agents/base/llamastack_agent
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
oc get route llamastack-agent -o jsonpath='{.spec.host}'
```

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2+2? Answer briefly."}'
```

## References

- [Llama Stack docs](https://llama-stack.readthedocs.io/)
- [llama-stack-client (PyPI)](https://pypi.org/project/llama-stack-client/)
