<div style="text-align: center;">

# OpenAI Responses Agent

</div>

---
Agent **without any agentic framework**: uses only the **OpenAI Python client** and **pure Python** (Responses API). No LlamaStack, LangChain, LlamaIndex, etc. Uses `AIAgent` with chat, tools, and Action/Observation loop. Compatible with OpenAI API or any OpenAI-compatible endpoint (e.g. `BASE_URL` override). Python 3.12+.

---

### Preconditions

- Copy/paste the `.env` file and set values for your environment
- Choose **local** or **RH OpenShift Cluster** and fill the needed values
- Run `./init.sh` to load values from `.env` into the environment

Copy `.env` file:

```bash
cp template.env agents/base/openai_responses_agent/.env
```

#### Local

Edit the `.env` file with your local configuration:

```
BASE_URL=http://localhost:8321
MODEL_ID=ollama/llama3.2:3b
API_KEY=not-needed
CONTAINER_IMAGE=not-needed
```

> **Local setup (Ollama):** Port and model name can differ depending on your setup (e.g. Llama Stack on port 8321 vs Ollama on 11434, or a different model ID). Check your running services and `run_llama_server.yaml` (if using Llama Stack) and set `BASE_URL` and `MODEL_ID` accordingly.

Or for **OpenAI API** directly:

```
BASE_URL=https://api.openai.com/v1
MODEL_ID=gpt-4o-mini
API_KEY=sk-...
CONTAINER_IMAGE=not-needed
```

#### OpenShift Cluster

Edit the `.env` file and fill in all required values:

```
API_KEY=your-api-key-here
BASE_URL=https://your-llama-stack-distribution.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/openai-responses-agent:latest
```

**Notes:**

- `API_KEY` – contact your cluster administrator
- `BASE_URL` – should end with `/v1`
- `MODEL_ID` – contact your cluster administrator
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

  - Quay.io: `quay.io/your-username/openai-responses-agent:latest`
  - Docker Hub: `docker.io/your-username/openai-responses-agent:latest`
  - GHCR: `ghcr.io/your-org/openai-responses-agent:latest`

Go to agent dir:

```bash
cd agents/base/openai_responses_agent
```

Create and activate a virtual environment (Python 3.12) in this directory using [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12
source .venv/bin/activate
```

(On Windows: `.venv\Scripts\activate`)

Make scripts executable:

```bash
chmod +x init.sh
```

Load values from `.env` into environment variables:

```bash
./init.sh
```

---

## Local usage (Ollama + LlamaStack Server)

Create package with agent and install it in venv:

```bash
uv pip install -e .
uv pip install ollama
```

Install Ollama from the [Ollama site](https://ollama.com/) or via Brew:

```bash
# brew install ollama
# or
curl -fsSL https://ollama.com/install.sh | sh
```

Pull required models:

```bash
ollama pull llama3.2:3b
ollama pull embeddinggemma:latest
```

Start Ollama service:

```bash
ollama serve
```

> **Keep this terminal open!**  
> Ollama needs to keep running.

Start LlamaStack server:

```bash
llama stack run ../../../run_llama_server.yaml
```

> **Keep this terminal open** – the server needs to keep running.  
> You should see output indicating the server started on `http://localhost:8321`.

Run the example:

```bash
uv run agents/base/openai_responses_agent/examples/execute_ai_service_locally.py
```

---

## Deployment on Red Hat OpenShift Cluster

Make deploy script executable:

```bash
chmod +x deploy.sh
```

Build image and deploy agent:

```bash
./deploy.sh
```

This will:

- Create Kubernetes secret for API key
- Build and push the Docker image
- Deploy the agent to OpenShift
- Create Service and Route

Get the route URL:

```bash
oc get route openai-responses-agent -o jsonpath='{.spec.host}'
```

Send a test request:

```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How much does a Lenovo Laptop cost and what are the reviews?"}'
```

---

## Agent-Specific Documentation

- [OpenAI Python client](https://github.com/openai/openai-python)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses/create)
- [Ollama](https://ollama.com/)
- [Ollama (Homebrew)](https://formulae.brew.sh/formula/ollama#default)
