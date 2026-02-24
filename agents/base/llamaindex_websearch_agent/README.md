<div style="text-align: center;">

![LlamaIndex Logo](/images/llamaindex_logo.svg)
# WebSearch Agent

</div>

---
### Preconditions:
- You need to copy/paste .env file and change its values to yours
- Decide what way you want to go `local` or `RH OpenShift Cluster` and fill needed values
- use `./init.sh` that will add those values from .env to environment variables



Copy .env file
```bash
cp template.env agents/base/llamaindex_websearch_agent/.env
```

#### Local
Edit the `.env` file with your local configuration:

```
BASE_URL=http://localhost:8321
MODEL_ID=ollama/llama3.2:3b
API_KEY=not-needed
CONTAINER_IMAGE=not-needed
```

#### OpenShift Cluster
Edit the `.env` file and fill in all required values:

```
API_KEY=your-api-key-here
BASE_URL=https://your-llama-stack-distribution.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/llamaindex-websearch-agent:latest
```

**Notes:**
- `API_KEY` - contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - contact your cluster administrator
- `CONTAINER_IMAGE` - full image path where the agent container will be pushed and pulled from.
  The image is built locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:
  - Quay.io: `quay.io/your-username/llamaindex-websearch-agent:latest`
  - Docker Hub: `docker.io/your-username/llamaindex-websearch-agent:latest`
  - GHCR: `ghcr.io/your-org/llamaindex-websearch-agent:latest`

Go to agent dir
```bash
cd agents/base/llamaindex_websearch_agent
```

Make scripts executable
```bash
chmod +x init.sh
```

Add to values from .env to environment variables
```bash
./init.sh
```

---

## Local usage (Ollama + LlamaStack Server)

Create package with agent and install it to venv
```bash
uv pip install -e .
```

```bash
uv pip install ollama
```

Install app from Ollama site or via Brew
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
>**Keep this terminal open!**\
> Ollama needs to keep running.

Start LlamaStack Server
```bash
llama stack run ../../../run_llama_server.yaml
```
> **Keep this terminal open** - the server needs to keep running.\
> You should see output indicating the server started on `http://localhost:8321`.

 Run the example:
```bash
uv run examples/execute_ai_service_locally.py
```

# Deployment on RedHat OpenShift Cluster
Login to OC
```bash
oc login -u "login" -p "password" https://super-link-to-cluster:111
```
Login ex. Docker
```bash
docker login -u='login' -p='password' quay.io
```

Make deploy file executable
```bash
chmod +x deploy.sh
```

Build image and deploy Agent
```bash
./deploy.sh
```

This will:
- Create Kubernetes secret for API key
- Build and push the Docker image
- Deploy the agent to OpenShift
- Create Service and Route

COPY the route URL and PASTE into the CURL below
```bash
oc get route llamaindex-websearch-agent -o jsonpath='{.spec.host}'
```

Send a test request:
```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is LangChain?"}'
```
---

## Agent-Specific Documentation
Each agent has detailed documentation for setup and deployment:
- https://ollama.com/
- https://formulae.brew.sh/formula/ollama#default
- https://docs.llamaindex.ai/
- https://docs.llamaindex.ai/en/stable/module_guides/workflow/
- https://llama-stack.readthedocs.io/