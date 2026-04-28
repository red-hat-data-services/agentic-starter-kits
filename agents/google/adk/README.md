<div style="text-align: center;">

<img src="/images/adk_logo.png" alt="Google ADK logo" width="100" height="100">

# Google ADK 2.0 Agent

</div>

---

## What this agent does

General-purpose agent using Google Agent Development Kit (ADK) 2.0 with a web search tool. It uses the LiteLLM model
connector to route inference through a LlamaStack server's OpenAI-compatible API endpoint.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) — for local container builds (Option A)
- [oc](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) — for
  OpenShift deployment
- [Helm](https://helm.sh/) — for deploying to Kubernetes/OpenShift
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell — on Windows,
  use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended)
  or [Git Bash](https://git-scm.com/downloads)

## Local Development

#### Initiating base

Here you copy .env.example file into .env

```bash
cd agents/google/adk
make init
```

Edit `.env` with your configuration, then:

#### Creating environment

Now you will remove old .venv and create new. Next dependencies will be installed.

```bash
make env
```

#### Setup Ollama

This will install ollama if it is not installed already. Then pull needed models for local work.
The default model is `llama3.1:8b`. To use a different model, pass `MODEL=`:
`make ollama MODEL=llama3.2:3b`

```bash
make ollama
```

#### Run llama server

> **Keep this terminal open** – the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.

```bash
make llama-server
```

#### Run the interactive web application

> **Keep this terminal open** – the app needs to keep running.
> You should see output indicating the app started on `http://localhost:8000`.

```bash
cd agents/google/adk
make run-app           # fails if port is already in use and print steps TO-DO
```

#### Interactive CLI

For terminal-based testing without a browser:

```bash
cd agents/google/adk
make run-cli
```

## Deploying to OpenShift

### Setup

```bash
cd agents/google/adk
make init
```

### Configuration

Edit `.env` with your model endpoint and container image:

```ini
API_KEY = your-api-key-here
BASE_URL = https://your-model-endpoint.com/v1
MODEL_ID = llama-3.1-8b-instruct
CONTAINER_IMAGE = quay.io/your-username/google-adk-agent:latest
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/google-adk-agent:latest`
    - Docker Hub: `docker.io/your-username/google-adk-agent:latest`
    - GHCR: `ghcr.io/your-org/google-adk-agent:latest`

  > **Note:** OpenShift must be able to pull the container image. Make the image **public**, or configure
  an [image pull secret](https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html)
  for private registries.

### Building the Container Image

Login to OC

```bash
oc login -u "login" -p "password" https://super-link-to-cluster:111
```

Login ex. Docker

```bash
docker login -u='login' -p='password' quay.io
```

#### Option A: Build locally and push to a registry

Requires Podman (or Docker) and a registry account (e.g., Quay.io).

```bash
make build    # builds the image locally
make push     # pushes to the registry specified in CONTAINER_IMAGE
```

#### Option B: Build in-cluster via OpenShift BuildConfig

No Podman, Docker, or registry account needed — just the `oc` CLI.

```bash
make build-openshift
```

After the build completes, set `CONTAINER_IMAGE` in your `.env` to the internal registry URL printed after the build.

### Deploying

#### Preview manifests (`make dry-run`)

```bash
make dry-run          # preview rendered Helm manifests (secrets redacted)
```

#### Deploy (`make deploy`)

```bash
make deploy
```

#### Verify deployment

After deploying, the application may take about a minute to become available while the pod starts up.

The route URL is printed after `make deploy`. You can also retrieve it manually:

```bash
oc get route google-adk-agent -o jsonpath='{.spec.host}'
```

#### Remove deployment (`make undeploy`)

```bash
make undeploy
```

See [OpenShift Deployment](../../../docs/openshift-deployment.md) for more details.

## Tests

```bash
make test
```

## API Endpoints

### POST /chat/completions

Non-streaming:

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Best server service?"}], "stream": false}'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Search for RedHat OpenShift"}], "stream": true}'
```

Pretty Printed Stream:

```bash
curl -sN -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Search for RedHat OpenShift"}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

### GET /health

```bash
curl http://localhost:8000/health
```

---

## Agent-Specific Documentation

### Architecture

This agent combines three key components:

1. **Google ADK 2.0 LlmAgent**: Manages the agent loop (reason, call tools, observe, answer)
2. **LiteLLM Model Connector**: Routes LLM calls to any OpenAI-compatible API (LlamaStack)
3. **InMemoryRunner**: Handles session management and agent execution

```text
User Input -> ADK LlmAgent -> LiteLLM -> LlamaStack (OpenAI API)
                 |                           |
                 v                           v
            Tool Calls              LLM Inference
                 |                           |
                 v                           v
          Tool Results              Model Response
                 |                           |
                 +------ Agent Loop ---------+
                              |
                              v
                       Final Response
```

### Configuration

**Environment Variables:**

| Variable          | Description        | Example                                               |
|-------------------|--------------------|-------------------------------------------------------|
| `BASE_URL`        | LLM API endpoint   | `http://localhost:8321/v1`                            |
| `MODEL_ID`        | Model identifier   | `ollama/llama3.1:8b`                                  |
| `API_KEY`         | API authentication | `not-needed-for-local-development` (local) or API key |
| `CONTAINER_IMAGE` | Container registry | `quay.io/user/google-adk-agent:latest`                |

**Customization:**

Edit `src/adk_agent/tools.py` to add new tools:

```python
def my_custom_tool(query: str) -> dict:
    """Description of what this tool does.

    Args:
        query: The input for the tool.

    Returns:
        A dict with status and result.
    """
    return {"status": "success", "result": "Tool output here"}
```

Then register it in `src/adk_agent/__init__.py`:

```python
from .tools import dummy_web_search, my_custom_tool

TOOLS = [dummy_web_search, my_custom_tool]
```

### Troubleshooting

**Error: "OPENAI_API_BASE not set"**

- Solution: Ensure `BASE_URL` is set in your `.env` file

**Tool calls returned as plain text instead of function calls**

- This can happen with smaller models (e.g., `llama3.2:3b`). Try a larger model or ensure
  the model supports function calling through LlamaStack.

**LiteLLM debug mode**

- To see the actual API requests being made, add to your code:
  ```python
  import litellm
  litellm._turn_on_debug()
  ```

### Additional Resources

- **Google ADK 2.0 Documentation**: https://google.github.io/adk-docs/2.0/
- **LiteLLM Documentation**: https://docs.litellm.ai/
- **Llama Stack Documentation**: https://llama-stack.readthedocs.io/
- **Ollama Documentation**: https://ollama.com/docs

---

## License

MIT License
