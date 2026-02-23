<div style="text-align: center;">

![LangGraph Logo](/images/langgraph_logo.png)
# ReACT Agent

</div>

---
### Preconditions:
- You need to copy/paste .env file and change its values to yours
- Decide what way you want to go `local` or `RH OpenShift Cluster` and fill needed values
- use `./init.sh` that will add those values from .env to environment variables



Copy .env file
```bash
cp template.env agents/base/langgraph_react_agent/.env
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
CONTAINER_IMAGE=quay.io/your-username/langgraph-react-agent:latest
```

**Notes:**
- `API_KEY` - contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - contact your cluster administrator
- `CONTAINER_IMAGE` - full image path where the agent container will be pushed and pulled from.
  The image is built locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`
  
  Examples:
  - Quay.io: `quay.io/your-username/langgraph-react-agent:latest`
  - Docker Hub: `docker.io/your-username/langgraph-react-agent:latest`
  - GHCR: `ghcr.io/your-org/langgraph-react-agent:latest`

Go to agent dir
```bash
cd agents/base/langgraph_react_agent
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
uv run agents/base/langgraph_react_agent/examples/execute_ai_service_locally.py
```

# Deployment on RedHat OpenShift Cluster
```bash

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

Get the route URL
```bash
oc get route langgraph-react-agent -o jsonpath='{.spec.host}'
```

Send a test request:
```bash
curl -X POST https://<YOUR_ROUTE_URL>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the best company? Answer with the first correct answer."}'
```

## Agent-Specific Documentation
Each agent has detailed documentation for setup and deployment:
- https://ollama.com/
- https://formulae.brew.sh/formula/ollama#default