<div style="text-align: center;">

![OpenAI Logo](/images/openai_logo.svg)

# Pure Responses Agent

</div>

---

## What this agent does

Minimal agent with no framework: only the OpenAI Python client and an Action/Observation loop with tools. Use with
OpenAI or any compatible API.

---

## Quick Start

```bash
cd agents/vanilla_python/openai_responses_agent
make init        # creates .env from .env.example
# Edit .env with your API_KEY, BASE_URL, MODEL_ID
make run         # starts on http://localhost:8080
```

## Configuration

### Local (with Ollama + Llama Stack)

```
API_KEY=not-needed
BASE_URL=http://localhost:8321/v1
MODEL_ID=ollama/llama3.2:3b
```

### Local (with OpenAI API)

```
API_KEY=sk-...
BASE_URL=https://api.openai.com/v1
MODEL_ID=gpt-4o-mini
```

See [Local Development](../../../docs/local-development.md) for Ollama + Llama Stack setup.

### OpenShift / Remote API

```
API_KEY=your-api-key-here
BASE_URL=https://your-llama-stack-distribution.com/v1
MODEL_ID=llama-3.1-8b-instruct
CONTAINER_IMAGE=quay.io/your-username/openai-responses-agent:latest
```

**Notes:**

- `API_KEY` - your API key or contact your cluster administrator
- `BASE_URL` - should end with `/v1`
- `MODEL_ID` - model identifier available on your endpoint
- `CONTAINER_IMAGE` – full image path where the agent container will be pushed and pulled from. The image is built
  locally, pushed to this registry, and then deployed to OpenShift.

  Format: `<registry>/<namespace>/<image-name>:<tag>`

  Examples:

    - Quay.io: `quay.io/your-username/openai-responses-agent:latest`
    - Docker Hub: `docker.io/your-username/openai-responses-agent:latest`
    - GHCR: `ghcr.io/your-org/openai-responses-agent:latest`

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
oc get route openai-responses-agent -o jsonpath='{.spec.host}'
```

Replace `http://localhost:8080` with `https://<YOUR_ROUTE_URL>` in the API examples below.

## API Endpoints

### POST /chat/completions

Non-streaming:

```bash
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "How much does a Lenovo Laptop cost and what are the reviews?"}], "stream": false}'
```

Streaming:

```bash
curl -sN -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "How much does a Lenovo Laptop cost and what are the reviews?"}], "stream": true}'
```

Pretty Printed Stream:

```bash
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "How much does a Lenovo Laptop cost and what are the reviews?"}], "stream": true}' |
   jq -R -r -j --stream 'scan("^data:(.*)")[] | fromjson.choices[0].delta.content // empty'
```

### GET /health

```bash
curl http://localhost:8080/health
```

## Playground UI

A browser-based chat interface is served directly by the agent at the root URL — no separate process needed.

### Running the Playground

Start the agent and open the root URL in your browser:

```bash
uvicorn main:app --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

A green dot in the header means the agent is connected and ready. Type a message and press **Enter** to send.

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

## Tests

```bash
make test
```

## Resources

- [OpenAI Python Client](https://github.com/openai/openai-python)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses/create)
