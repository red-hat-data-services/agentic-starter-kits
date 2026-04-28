<div style="text-align: center;">

# Simple Tool Calling Agent

</div>

---

## What this agent does

Tool-calling agent built with Langflow's visual flow builder. It calls external APIs as tools (weather forecasts,
national park data) and reasons over the results to answer user questions. Includes Langfuse v3 tracing out of the box.

**Example queries:**

- *"Can I go walking in Boston tomorrow at 3 PM?"*
- *"I want to go hiking near Denver this weekend. What day is best?"*
- *"Is it a good day for a picnic in San Francisco?"*

### Tools

| Tool                | API        | Description                                            |
|---------------------|------------|--------------------------------------------------------|
| Open-Meteo Forecast | Open-Meteo | Daily weather forecast (temp, wind, precipitation, UV) |
| NPS Search Parks    | NPS API    | Search national parks by state                         |
| NPS Park Alerts     | NPS API    | Active alerts and closures for a park                  |

> **Note:** Unlike other agents in this repo, Langflow agents do not deploy a custom container. The "agent" is a JSON
> flow definition imported into an existing Langflow instance. There is no Dockerfile, Helm chart, or FastAPI
> application.

---

## Prerequisites

- [Podman](https://podman.io/) + [podman-compose](https://github.com/containers/podman-compose) — for running the local
  stack
- [GNU Make](https://www.gnu.org/software/make/) and a bash-compatible shell — on Windows,
  use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (recommended)
  or [Git Bash](https://git-scm.com/downloads)

### Installing Podman

**macOS:**

```bash
brew install podman             # install podman runtime
brew install podman-compose     # install compose plugin
podman machine init             # create a Linux VM (podman runs containers in a VM on macOS)
podman machine start            # start the VM
```

**Linux:**

```bash
sudo dnf install -y podman      # install podman runtime
uv pip install podman-compose   # install compose plugin
sudo systemctl start podman     # start the podman service
```

## Local Development

#### Initiating base

Here you copy .env.example file into .env and generate Langfuse secrets

```bash
cd agents/langflow/simple_tool_calling_agent
make init
```

#### Setup Ollama

This will install ollama if it is not installed already. Then pull needed models for local work.
The default model is `qwen2.5:7b`. To use a different model, pass `MODEL=`:
`make ollama MODEL=llama3.1:8b`

```bash
make ollama
```

#### Run llama server

> **Keep this terminal open** – the server needs to keep running.
> You should see output indicating the server started on `http://localhost:8321`.

```bash
make llama-server
```

#### Run the Langflow stack

> **Keep this terminal open** – the stack needs to keep running.
> This starts Langflow + PostgreSQL + Langfuse v3 (ClickHouse, MinIO, Redis).

```bash
make run
```

#### Import the flow

1. Open http://localhost:7860
2. On first launch, Langflow asks you to create a flow — create a **Blank Flow** (this is just to get past the initial
   screen)
3. Click the **Langflow icon** (top left) to go to the projects page
4. Click **Upload Flow** and select `flows/outdoor-activity-agent.json`

#### Configuration

Configure the flow components:

| Component        | Field      | Value                                     |
|------------------|------------|-------------------------------------------|
| KServe vLLM      | api_base   | http://host.containers.internal:8321/v1   |
| KServe vLLM      | model_name | ollama/qwen2.5:7b                         |
| KServe vLLM      | api_key    | not-needed-for-local-development          |
| NPS Search Parks | api_key    | Get one free at https://developer.nps.gov |
| NPS Park Alerts  | api_key    | Same NPS key as above                     |

#### Pointing to a locally hosted model

See [Local Development](../../../docs/local-development.md) for Ollama + Llama Stack setup for local model serving.

**Notes:**

- `api_base` — use `host.containers.internal` instead of `localhost` so containerized Langflow can reach Llama Stack
  running on the host
- `api_key` — Llama Stack doesn't require authentication, so any non-empty string works
- `model_name` — not all models handle tool calling well. `qwen2.5:7b` and `llama3.1:8b` are known to work

#### Pointing to a remotely hosted model

Update the **KServe vLLM** component in the Langflow UI:

| Field      | Value                  |
|------------|------------------------|
| api_base   | your-model-endpoint/v1 |
| model_name | your-model-id          |
| api_key    | your-api-key           |

#### Running the Agent

Run the agent from the Langflow UI by clicking the **Play** button.

#### Tracing

Langfuse v3 tracing is included in the local stack and starts automatically. No additional setup needed.

- **Langfuse UI**: http://localhost:3000
- **Login**: admin@langflow.local / password auto-generated in `local/.env`

After running the agent, select the **Langflow Agent** project and click **Traces** to see agent executions — LLM calls,
tool invocations, inputs, and outputs.

#### Stopping the stack

```bash
make stop        # stop services, keep data
make clean       # stop services, remove all data
```

| Data                                 | `make stop` | `make clean`                   |
|--------------------------------------|-------------|--------------------------------|
| Imported Langflow flows              | Kept        | **Deleted** (re-import needed) |
| Langfuse traces (ClickHouse + MinIO) | Kept        | **Deleted**                    |
| PostgreSQL data                      | Kept        | **Deleted**                    |
| Redis cache                          | Kept        | **Deleted**                    |
| `local/.env` config                  | Kept        | **Deleted**                    |

## Deploying to Cluster

There is nothing to build or deploy — no Dockerfiles, no Helm charts, no k8s manifests. This agent assumes Langflow,
Langfuse, and an LLM (LlamaStack/KServe) are already running on the cluster. You just import the flow JSON into the
existing Langflow instance and configure it.

### Login to OC

```bash
oc login -u "login" -p "password" https://super-link-to-cluster:111
```

### Finding cluster endpoints

Reach out to your cluster admin for the Langflow URL and LlamaStack endpoint/model names. If you have `oc` CLI access,
you can find them yourself:

```bash
# Langflow UI URL
oc get routes --all-namespaces | grep langflow

# LlamaStack URL
oc get routes --all-namespaces | grep llama

# KServe model (internal endpoint + model name)
oc get inferenceservice --all-namespaces
```

### Steps

1. Open the Langflow UI on your cluster
2. Import `flows/outdoor-activity-agent.json`
3. Configure the flow components:
    - **KServe vLLM**: set `api_base` and `model_name`. You can connect through LlamaStack or directly to KServe:

      | Option | api_base | model_name |
            |--------|----------|------------|
      | Via LlamaStack (external route) | https://\<llamastack-route-host\>/v1 | vllm//mnt/models |
      | Via LlamaStack (internal) | http://llamastack-service.\<namespace\>.svc.cluster.local:8321/v1 | vllm//mnt/models |
      | Direct to KServe (internal) | http://\<model\>-predictor.\<namespace\>.svc.cluster.local:8080/v1 | /mnt/models |

      Use the external route if Langflow can't reach LlamaStack internally (network policy). Use `oc get routes` and
      `oc get inferenceservice` to find the actual hostnames and namespaces.
    - **NPS Search Parks**: set `api_key` (get one free at https://developer.nps.gov)
    - **NPS Park Alerts**: set `api_key` (same NPS key)
4. Run the agent

## API Endpoints

### POST /api/v1/run/\<flow-id\>

```bash
curl -X POST http://localhost:7860/api/v1/run/<flow-id> \
  -H "Content-Type: application/json" \
  -d '{"input_value": "What is the best day to hike near Denver?", "output_type": "chat", "input_type": "chat"}'
```

Replace `<flow-id>` with the flow ID from the Langflow UI. You can find it in the browser URL bar when you open the
flow — e.g., `http://localhost:7860/flow/27e7203d-b2b1-4700-962a-144a66155f14` → the flow ID is
`27e7203d-b2b1-4700-962a-144a66155f14`.

On the cluster, replace `localhost:7860` with your cluster's Langflow route URL.

## Exporting Flows

When exporting a flow from Langflow, API keys and secrets can be embedded in the exported JSON file. To avoid leaking
secrets:

1. In the export dialog, **uncheck "Save with API keys"** — this excludes all API keys from the exported file
2. If you already exported with keys included, you can strip them manually by searching for `"api_key"` fields in the
   JSON and clearing their `"value"` entries

## Resources

- [Langflow Documentation](https://docs.langflow.org/)
- [Open-Meteo](https://open-meteo.com/) — Weather and air quality (free, no key required)
- [National Park Service API](https://developer.nps.gov) — Park search and alerts (free key required)
