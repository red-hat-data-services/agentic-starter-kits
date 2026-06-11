# How to Deploy Claude Code on OpenShift

A step-by-step guide to build, test, and deploy the Claude Code container image.

## Licensing Notice

**Do not redistribute built container images.** The Containerfile installs Claude Code at build time via Anthropic's native installer. The resulting image contains Anthropic's proprietary binary, which is subject to their [commercial terms](https://code.claude.com/docs/en/legal-and-compliance) ("All rights reserved"). Building the image yourself for internal use is permitted, but redistributing the built image (e.g., pushing to a public registry) is not authorized.

## Prerequisites

- `podman` installed locally (on macOS, you also need to run `podman machine init` and `podman machine start` before building)
- `oc` CLI installed and logged into your OpenShift cluster
- An Anthropic API key, a GCP service account key for Vertex AI, or a vLLM/OGX endpoint (no Anthropic credentials needed)
- The Containerfile and entrypoint.sh files

---

## Option A: Deploy with Anthropic API Key

### 0. Get your Anthropic API key

1. Go to [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign in or create an account
3. Navigate to **API Keys** in the left sidebar
4. Click **Create Key** and give it a name
5. Copy the key (it starts with `sk-ant-api03-...`)

**Note**: You need a paid account with credits to use the API.

### 1. Build and test locally

```bash
# Build
podman build -t claude-code:latest -f Containerfile .

# Build with a specific Claude Code version
podman build --build-arg CLAUDE_CODE_VERSION=2.1.123 -t claude-code:2.1.123 -f Containerfile .

# Test (non-interactive)
podman run --rm \
  -e ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE" \
  claude-code:latest \
  claude -p "What is 2+2?"
```

### 2. Create OpenShift namespace

```bash
oc new-project my-claude-project
```

### 3. Create the API key secret

```bash
oc create secret generic claude-credentials \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE"
```

### 4. Apply the deployment manifest

```bash
oc apply -f deployment.yaml
```

### 5. Build the image on OpenShift

```bash
oc start-build claude-code --from-dir=. --follow
```

**Rebuilding:** After running `oc start-build` to rebuild the image (e.g., after modifying the Containerfile), the running pod will not pick up the new image automatically. Re-apply the deployment manifest and restart:

```bash
oc apply -f deployment.yaml
oc rollout restart deployment/claude-code
```

### 6. Wait for deployment and test

```bash
# Wait for rollout
oc rollout status deployment/claude-code

# Test using the claude-run wrapper (includes all configured args)
oc exec deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2?"
'
```

**Note**: The `claude-run` wrapper automatically includes all container-configured arguments (permission bypass, MCP config, model selection, etc.). You can also source the environment directly:

```bash
oc exec deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS -p "What is 2+2?"
'
```

### 7. Interactive mode

For a full interactive Claude Code experience with multi-turn conversations:

```bash
# Local interactive mode
podman run -it --rm \
  -e ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE" \
  -v $(pwd):/workspace:z \
  claude-code:latest \
  claude

# OpenShift interactive mode (uses claude-run for proper config)
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run
'
```

**Note**: Interactive mode requires a TTY, so use `-it` flags with podman and `oc exec`.

### 8. Debug mode

To see detailed logging of Claude Code activity, use the `--debug` flag:

```bash
# Enable full debug logging
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  claude --debug api
'
```

Debug logs are written to a file. To monitor the logs in real-time, open a second terminal and run:

```bash
oc exec deployment/claude-code -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

---

## Option B: Deploy with Vertex AI

### 0. Get your GCP service account key

You need a GCP service account with Vertex AI access. Choose one of these methods:

**Option 1: Create a new service account in GCP Console**

1. Go to [GCP Console](https://console.cloud.google.com)
2. Select your project (must have Vertex AI API enabled)
3. Navigate to **IAM & Admin → Service Accounts**
4. Click **+ CREATE SERVICE ACCOUNT**
   - Name: `claude-code-user` (or your preferred name)
   - Grant role: **Vertex AI User** (`roles/aiplatform.user`)
5. Click on the service account → **Keys** tab
6. Click **Add Key → Create new key → JSON**
7. The key file downloads automatically - save it securely

**Option 2: Use gcloud CLI**

```bash
# Create service account
gcloud iam service-accounts create claude-code-user \
  --display-name="Claude Code User"

# Grant Vertex AI access
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:claude-code-user@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Create and download key
gcloud iam service-accounts keys create ~/claude-vertex-key.json \
  --iam-account=claude-code-user@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

**Note**: Creating service accounts requires **IAM Admin** or **Service Account Admin** permissions in the GCP project.

**Alternative: Application Default Credentials (ADC)**

If you already have credentials via `gcloud auth application-default login`, you can use your ADC file (typically at `~/.config/gcloud/application_default_credentials.json`) in place of a service account key. Substitute this path wherever the instructions reference your service account key file.

**Important:** ADC credentials are user-scoped and typically carry broader permissions than a dedicated service account. Use ADC for local development and testing only. For shared or production clusters, create a least-privilege service account with only the **Vertex AI User** role as described above.

### 1. Build and test locally

```bash
# Build
podman build -t claude-code:latest -f Containerfile .

# Build with a specific Claude Code version
podman build --build-arg CLAUDE_CODE_VERSION=2.1.123 -t claude-code:2.1.123 -f Containerfile .

# Test (non-interactive)
podman run --rm \
  -e CLAUDE_CODE_USE_VERTEX=1 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id" \
  -e CLOUD_ML_REGION="global" \
  -e GOOGLE_APPLICATION_CREDENTIALS="/var/secrets/google/key.json" \
  -v /path/to/your-service-account-key.json:/var/secrets/google/key.json:ro,z \
  claude-code:latest \
  claude -p "What is 2+2?"
```

### 2. Create OpenShift namespace

```bash
oc new-project my-claude-project
```

### 3. Create the GCP credentials secret

```bash
oc create secret generic claude-vertex-credentials \
  --from-file=key.json=/path/to/your-service-account-key.json
```

### 4. Apply the Vertex AI deployment manifest and update the ConfigMap

Apply the manifest first to create all the resources, then immediately patch the ConfigMap with your actual project details before the pod starts using them:

```bash
oc apply -f deployment-vertex.yaml
```

```bash
oc patch configmap claude-vertex-config \
  -p '{"data":{"ANTHROPIC_VERTEX_PROJECT_ID":"your-gcp-project-id","CLOUD_ML_REGION":"global"}}'
```

Restart the deployment so pods pick up the patched ConfigMap values:

```bash
oc rollout restart deployment/claude-code-vertex
```

### 5. Build the image on OpenShift

```bash
oc start-build claude-code --from-dir=. --follow
```

**Rebuilding:** After running `oc start-build` to rebuild the image (e.g., after modifying the Containerfile), the running pod will not pick up the new image automatically. Re-apply the deployment manifest and restart:

```bash
oc apply -f deployment-vertex.yaml
oc rollout restart deployment/claude-code-vertex
```

### 6. Wait for deployment and test

```bash
oc rollout status deployment/claude-code-vertex

# Test using the claude-run wrapper (includes all configured args)
oc exec deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2?"
'
```

**Note**: The `claude-run` wrapper automatically includes all container-configured arguments (permission bypass, MCP config, model selection, etc.). You can also source the environment directly:

```bash
oc exec deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS -p "What is 2+2?"
'
```

**Note on model selection:** On Vertex AI, the default `sonnet` model alias may resolve to an older model than on the direct Anthropic API. If you want a specific model version, set the `CLAUDE_MODEL` environment variable in your deployment manifest or patch it directly:

```bash
oc set env deployment/claude-code-vertex CLAUDE_MODEL=claude-sonnet-4-6
```

### 7. Interactive mode

For a full interactive Claude Code experience with multi-turn conversations:

```bash
# Local interactive mode
podman run -it --rm \
  -e CLAUDE_CODE_USE_VERTEX=1 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id" \
  -e CLOUD_ML_REGION="global" \
  -e GOOGLE_APPLICATION_CREDENTIALS="/var/secrets/google/key.json" \
  -v /path/to/your-service-account-key.json:/var/secrets/google/key.json:ro,z \
  -v $(pwd):/workspace:z \
  claude-code:latest \
  claude

# OpenShift interactive mode (uses claude-run for proper config)
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run
'

# Alternative: source env.sh directly
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS
'
```

**Note**: Interactive mode requires a TTY, so use `-it` flags with podman and `oc exec`.

### 8. Debug mode

To see detailed logging of Claude Code activity, use the `--debug` flag:

```bash
# Enable full debug logging
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  claude --debug api
'
```

Debug logs are written to a file. To monitor the logs in real-time, open a second terminal and run:

```bash
oc exec deployment/claude-code-vertex -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

---

## Option C: Deploy with vLLM (Direct Connection)

This option connects Claude Code directly to a vLLM server that supports the Anthropic Messages API (`/v1/messages` endpoint).

### Prerequisites

- A vLLM server with `/v1/messages` endpoint support
- The vLLM model must have a **context window of at least 32K tokens** (Claude Code's system prompt is ~23K tokens). However, for realistic coding work, **128K+ tokens is strongly recommended** since CLAUDE.md, skills, file listings, and conversation easily push input past 100K tokens
- Network connectivity from your OpenShift cluster to the vLLM server

**Important**: Claude Code internally uses model aliases (haiku, sonnet, opus) for certain operations. When using vLLM, you must override these aliases using environment variables (see step 3 below), otherwise Claude Code will attempt to use Anthropic model names which will result in 404 errors.

**Network connectivity**: If the vLLM server is outside the cluster (e.g., on EC2 or another cloud), verify that the pod can reach it. Common causes of connection failure include security group rules, network policies, and firewalls. To test connectivity from inside the pod:

```bash
# Find the cluster's egress IP
oc exec deployment/claude-code-vllm -- curl -s ifconfig.me

# Test connectivity to the vLLM server
oc exec deployment/claude-code-vllm -- curl -s -o /dev/null -w "%{http_code}" http://YOUR_VLLM_HOST:8000/v1/models
```

If the vLLM server uses IP-based access rules, add the cluster egress IP to the allow list (e.g., AWS security group inbound rule on TCP port 8000).

**Note:** Claude Code is designed and tested for use with Anthropic's Claude models. Open source models may produce lower quality results, particularly for complex multi-step tasks. Including language runtimes in the container (see [Extending the Container Image](#extending-the-container-image)) helps because the agent can run tests and catch its own mistakes.

### 1. Build and test locally

```bash
# Build
podman build -t claude-code:latest -f Containerfile .

# Build with a specific Claude Code version
podman build --build-arg CLAUDE_CODE_VERSION=2.1.123 -t claude-code:2.1.123 -f Containerfile .

# Test (non-interactive) - replace YOUR_VLLM_ENDPOINT and YOUR_MODEL_ID
podman run --rm \
  -e ANTHROPIC_BASE_URL="https://YOUR_VLLM_ENDPOINT" \
  -e ANTHROPIC_API_KEY="fake" \
  claude-code:latest \
  claude --model YOUR_MODEL_ID -p "What is 2+2?"
```

### 2. Create OpenShift namespace

```bash
oc new-project my-claude-project
```

### 3. Update the deployment manifest

Edit `deployment-vllm.yaml` and update:

- `ANTHROPIC_BASE_URL`: Your vLLM server URL (e.g., `https://vllm.apps.cluster.domain`)
- `ANTHROPIC_CUSTOM_MODEL_OPTION`: Your model ID (bare model name, no prefix)
- Model alias overrides (required to prevent 404 errors):
  - `ANTHROPIC_DEFAULT_HAIKU_MODEL`: Set to your vLLM model ID
  - `ANTHROPIC_DEFAULT_SONNET_MODEL`: Set to your vLLM model ID
  - `ANTHROPIC_DEFAULT_OPUS_MODEL`: Set to your vLLM model ID
- `claude-vllm-settings` ConfigMap: Set the `model` field to your model ID

**Context window configuration**: Claude Code defaults to a 180K context window, which causes failures on models with smaller windows (e.g., 131K). Configure these three env vars in the `claude-vllm-settings` ConfigMap or the Deployment env section:

- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`: Set to your model's actual context window in tokens (e.g., `131072` for a 131K model). Do not pre-subtract output tokens.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS`: Set to your desired output budget (e.g., `28000`).
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`: Controls when autocompaction triggers. Set so that the remaining headroom exceeds the output budget. Formula: `percentage <= (context_window - max_output_tokens) / context_window * 100`

Example values:

| Model | Context | AUTO_COMPACT_WINDOW | MAX_OUTPUT_TOKENS | AUTOCOMPACT_PCT |
|-------|---------|--------------------|--------------------|-----------------|
| RedHatAI/Qwen3.6-35B-A3B-NVFP4 | 131K | 131072 | 28000 | 75 |
| Qwen/Qwen3-235B-A22B | 131K | 131072 | 28000 | 75 |
| openai/gpt-oss-120b | 131K | 131072 | 28000 | 75 |
| ibm-granite/granite-4.1-8b-instruct | 524K | 524288 | 64000 | 83 |
| meta-llama/Llama-4-Maverick-17B-128E | 1,048K | 1048576 | 64000 | 83 |

Models with 500K+ context can use the default 83% threshold. Models with smaller context windows need a lower percentage to leave sufficient headroom for output tokens.

### 4. Apply the deployment manifest

```bash
oc apply -f deployment-vllm.yaml
```

### 5. Build the image on OpenShift

```bash
oc start-build claude-code --from-dir=. --follow
```

**Rebuilding:** After running `oc start-build` to rebuild the image (e.g., after modifying the Containerfile), the running pod will not pick up the new image automatically. Re-apply the deployment manifest and restart:

```bash
oc apply -f deployment-vllm.yaml
oc rollout restart deployment/claude-code-vllm
```

### 6. Wait for deployment and test

```bash
# Wait for rollout
oc rollout status deployment/claude-code-vllm

# Test
oc exec deployment/claude-code-vllm -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2?"
'
```

### 7. Test the vLLM endpoint directly

If you're troubleshooting or want to verify the vLLM server supports the Anthropic Messages API:

```bash
# Test /v1/messages endpoint
curl -s -X POST "https://YOUR_VLLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
  }'

# Test with tool calling (Claude Code uses tools extensively)
curl -s -X POST "https://YOUR_VLLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "List files in the current directory"}],
    "tools": [{"name": "bash", "description": "Run a bash command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}]
  }'

# Test streaming (Claude Code uses streaming by default)
curl -s -X POST "https://YOUR_VLLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "max_tokens": 100,
    "stream": true,
    "messages": [{"role": "user", "content": "Say hello"}]
  }'

# Check available models
curl -s "https://YOUR_VLLM_ENDPOINT/v1/models"

# Check health endpoint
curl -s "https://YOUR_VLLM_ENDPOINT/health"
```

### 8. Interactive mode

```bash
# Local interactive mode
podman run -it --rm \
  -e ANTHROPIC_BASE_URL="https://YOUR_VLLM_ENDPOINT" \
  -e ANTHROPIC_API_KEY="fake" \
  -v $(pwd):/workspace:z \
  claude-code:latest \
  claude --model YOUR_MODEL_ID

# OpenShift interactive mode
oc exec -it deployment/claude-code-vllm -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run
'
```

### 9. Debug mode

```bash
# Enable full debug logging
oc exec -it deployment/claude-code-vllm -- bash -c '
  export HOME=/home/claude-agent
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-vllm -- bash -c '
  export HOME=/home/claude-agent
  claude --debug api
'
```

Debug logs are written to a file. To monitor the logs in real-time, open a second terminal and run:

```bash
oc exec deployment/claude-code-vllm -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

---

## Option D: Deploy with vLLM via OGX Gateway

This option uses OGX (from RHOAI) as an API gateway between Claude Code and vLLM. OGX provides the Anthropic Messages API (`/v1/messages`) with native passthrough to vLLM.

**Architecture**: Claude Code → OGX (API Gateway) → vLLM (Model Server)

**Note**: This example uses OGX 1.0.2. Adjust image tags and configuration as needed for other versions.

### Prerequisites

- **OGX with PostgreSQL**: Some versions of OGX require PostgreSQL as the storage backend. Check your OGX version's requirements and deploy accordingly before proceeding.
- A vLLM server accessible from OGX
- The vLLM model must have a **context window of at least 32K tokens** (Claude Code's system prompt is ~23K tokens). However, for realistic coding work, **128K+ tokens is strongly recommended** since CLAUDE.md, skills, file listings, and conversation easily push input past 100K tokens

**Important**: Claude Code internally uses model aliases (haiku, sonnet, opus) for certain operations. When using OGX with vLLM, you must override these aliases using environment variables (see step 1 below), otherwise Claude Code will attempt to use Anthropic model names which will result in 404 errors.

**Note:** Claude Code is designed and tested for use with Anthropic's Claude models. Open source models may produce lower quality results, particularly for complex multi-step tasks. Including language runtimes in the container (see [Extending the Container Image](#extending-the-container-image)) helps because the agent can run tests and catch its own mistakes.

### 1. Update the Claude Code deployment manifest

Edit `deployment-ogx-vllm.yaml` and update:

- `ANTHROPIC_BASE_URL`: Your OGX route URL (e.g., `https://ogx-my-claude-project.apps.cluster.domain`)
- `ANTHROPIC_CUSTOM_MODEL_OPTION`: Use `vllm/<model-id>` format (OGX routing prefix)
- Model alias overrides (required to prevent 404 errors):
  - `ANTHROPIC_DEFAULT_HAIKU_MODEL`: Set to `vllm/<model-id>`
  - `ANTHROPIC_DEFAULT_SONNET_MODEL`: Set to `vllm/<model-id>`
  - `ANTHROPIC_DEFAULT_OPUS_MODEL`: Set to `vllm/<model-id>`
- `claude-ogx-vllm-settings` ConfigMap: Set the `model` field to `vllm/<model-id>`

**Important**: OGX uses the `vllm/` prefix to route requests to the vLLM backend. Always use `vllm/<model-id>` format in this deployment.

### 2. Apply the deployment manifest

```bash
oc apply -f deployment-ogx-vllm.yaml
```

### 3. Build the Claude Code image

```bash
oc start-build claude-code --from-dir=. --follow
```

**Rebuilding:** After running `oc start-build` to rebuild the image (e.g., after modifying the Containerfile), the running pod will not pick up the new image automatically. Re-apply the deployment manifest and restart:

```bash
oc apply -f deployment-ogx-vllm.yaml
oc rollout restart deployment/claude-code-ogx-vllm
```

### 4. Wait for deployment and test

```bash
# Wait for rollout
oc rollout status deployment/claude-code-ogx-vllm

# Test
oc exec deployment/claude-code-ogx-vllm -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2?"
'
```

### 5. Test the OGX endpoint

You can verify OGX is correctly routing to vLLM:

```bash
# Get OGX route URL
OGX_URL=$(oc get route ogx -o jsonpath='{.spec.host}')

# Check OGX health
curl -s "https://$OGX_URL/v1/health"

# Check available models (should show your vLLM model)
curl -s "https://$OGX_URL/v1/models"

# Test /v1/messages endpoint through OGX
# Note: Use vllm/<model-id> format for OGX routing
curl -s -X POST "https://$OGX_URL/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "vllm/YOUR_MODEL_ID",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
  }'

# Test with tool calling (Claude Code uses tools extensively)
curl -s -X POST "https://$OGX_URL/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "vllm/YOUR_MODEL_ID",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "List files in the current directory"}],
    "tools": [{"name": "bash", "description": "Run a bash command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}]
  }'

# Test streaming (Claude Code uses streaming by default)
curl -s -X POST "https://$OGX_URL/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "vllm/YOUR_MODEL_ID",
    "max_tokens": 100,
    "stream": true,
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

### 6. Understanding OGX Logs

When monitoring OGX logs, you may see some 404 responses. This is normal:

```bash
oc logs deployment/ogx --tail=50
```

**Normal log pattern:**

```text
HEAD / 404        # Claude Code HTTP client probing
POST /v1/messages 404  # Initial probes (2x)
POST /v1/messages 200  # Successful request with "Using native /v1/messages passthrough"
```

The 404s are caused by Claude Code's HTTP client probing behavior and do not indicate errors. The key indicator of success is seeing `Using native /v1/messages passthrough` followed by a 200 response.

### 7. Interactive mode

```bash
# OpenShift interactive mode
oc exec -it deployment/claude-code-ogx-vllm -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run
'
```

### 8. Debug mode

```bash
# Enable full debug logging
oc exec -it deployment/claude-code-ogx-vllm -- bash -c '
  export HOME=/home/claude-agent
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-ogx-vllm -- bash -c '
  export HOME=/home/claude-agent
  claude --debug api
'
```

Debug logs are written to a file. To monitor the logs in real-time, open a second terminal and run:

```bash
oc exec deployment/claude-code-ogx-vllm -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

You can also check OGX logs for request routing information:

```bash
oc logs deployment/ogx --tail=50
```

---

## Security Considerations

### SKIP_PERMISSIONS

The deployment manifests set `SKIP_PERMISSIONS=true` by default, which passes `--dangerously-skip-permissions` to Claude Code. This disables all permission prompts, including file-system write confirmations and confirmation of potentially destructive operations (e.g., `git push --force`).

**Why it's enabled by default:**

- The container runs as non-root with dropped capabilities and seccomp profiles
- Claude only has access to the isolated `/workspace` PVC, not host filesystems
- Permission prompts don't work well in non-interactive `oc exec` scenarios
- One of the main advantages of running Claude Code in an isolated container is enabling less-interrupted workflows

**Tradeoffs to consider:**

Running in an isolated container removes much of the reason you would normally keep permission checks in place: the container cannot access data that is not explicitly mounted into it. However, skipping permissions also disables guardrails against destructive operations on external services the agent can reach, such as force-pushing to a Git remote or making unintended API calls via MCP servers. If you are running interactively and want an extra layer of confirmation, you can disable `SKIP_PERMISSIONS`. But for headless or automated usage, permission prompts are not practical, and you should rely on the repository safeguards described below instead.

To disable, set `SKIP_PERMISSIONS=false` in the deployment manifest or remove the environment variable entirely.

### Repository Safeguards

When an AI agent has push access to a Git repository, you should ensure the repository itself has protections against mistakes. This is especially important when permission checks are disabled (`SKIP_PERMISSIONS=true`) and when using less capable models that are more likely to make errors such as committing directly to main, force-pushing, or merging their own PRs.

**Recommended protections:**

- **Branch protection rules**: Protect your main/default branch so that direct pushes are blocked. This forces all changes through pull requests. On GitHub, configure this under Settings > Branches > Branch protection rules.
- **Required pull request reviews**: Require at least one approval from someone other than the PR author before merging. This prevents the agent (or anyone) from opening and immediately merging a PR without human review.
- **Limit PAT scope**: When creating the GitHub Personal Access Token used by the agent, grant only the minimum permissions needed. For example, if the agent only needs to open PRs but not merge them, do not grant the PAT merge permissions. See [GitHub's documentation on token scopes](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) for fine-grained token options.
- **Status checks**: Require CI checks (tests, linting) to pass before a PR can be merged, so that broken code cannot be merged even if a review is approved.

These protections apply regardless of whether you are using Claude Code or any other AI coding tool. They are standard best practices for collaborative development, but become critical when an automated agent has commit and push access.

### Credential Isolation

When credentials such as GitHub PATs or API tokens are passed as environment variables or written to files inside the container, the agent can read them directly. This means the agent could inadvertently expose credentials in conversation output, commit messages, or through MCP server calls. This is a known limitation of the approach described in this guide.

For many use cases, this risk is acceptable when combined with the safeguards above: limiting PAT scope to the minimum required permissions, protecting branches, and requiring PR reviews. However, for environments with strict security requirements, the ideal approach is to isolate the agent from the credentials it depends on, so that it can use tools (like git push or GitHub APIs) without being able to see or exfiltrate the underlying secrets.

Container isolation solutions are actively exploring ways to provide this kind of separation. If credential isolation is a requirement for your deployment, consider evaluating such solutions as they mature.

---

## Customization

### Session Persistence

By default, Claude Code session history and memory persist across pod restarts. This is enabled via the `CLAUDE_CONFIG_DIR` environment variable, which points to `/workspace/.claude/` (inside the workspace PVC).

**Directory structure:**

```text
/workspace/                      ← PVC mount (persistent)
├── .claude/                     ← Global config (CLAUDE_CONFIG_DIR)
│   ├── settings.json            ← ConfigMap mount
│   ├── skills/                  ← ConfigMap mount
│   ├── memory/                  ← Persisted (global memory)
│   └── projects/                ← Persisted (session history)
└── projects/                    ← WORKDIR (where users run Claude)
    └── .claude/                 ← Local auto-memory (separate from global)
```

This structure separates global config (`/workspace/.claude/`) from local auto-memory (`/workspace/projects/.claude/`), mirroring the experience of running Claude Code locally on a laptop.

**What persists:**

| Data | Location | Persisted? |
|------|----------|------------|
| Session history | `/workspace/.claude/projects/` | ✅ Yes |
| Global memory | `/workspace/.claude/memory/` | ✅ Yes |
| Local auto-memory | `/workspace/projects/.claude/` | ✅ Yes |
| Project files | `/workspace/projects/` | ✅ Yes |
| Skills | `/workspace/.claude/skills/` | ConfigMap (re-mounted each restart) |
| Settings | `/workspace/.claude/settings.json` | ConfigMap (re-mounted each restart) |

**How it works:**

1. The `CLAUDE_CONFIG_DIR` environment variable tells Claude Code to store global state in `/workspace/.claude/`
2. The entrypoint creates a symlink: `~/.claude` → `/workspace/.claude/`
3. The `WORKDIR` is `/workspace/projects/`, so local auto-memory goes to `/workspace/projects/.claude/`
4. The `/workspace` directory is backed by a PVC, so all session data persists
5. Skills and settings are ConfigMap mounts that overlay specific paths within the PVC

**User experience:**

```bash
# Session 1: Have a conversation
oc exec -it deployment/claude-code -- bash
~/.claude/claude-run
# ... conversation with Claude ...
# Exit and pod restarts

# Session 2: Claude remembers the previous conversation
oc exec -it deployment/claude-code -- bash
~/.claude/claude-run
# Claude can reference prior context
```

**Disabling persistence:**

To disable session persistence (ephemeral sessions only), set `CLAUDE_CONFIG_DIR` to a non-PVC path:

```yaml
env:
  - name: CLAUDE_CONFIG_DIR
    value: "/tmp/.claude"
```

### Injecting Skills

Skills allow you to extend Claude Code with custom instructions and capabilities. Skills are injected at deploy time via ConfigMap or PVC mount.

**Skills directory structure:**

```text
~/.claude/skills/
├── my-skill/
│   └── SKILL.md
└── another-skill/
    └── SKILL.md
```

**Mount path:** `/workspace/.claude/skills` (accessible via `~/.claude/skills/` symlink)

Claude Code auto-discovers skills from `~/.claude/skills/`. Each skill is a subdirectory containing a `SKILL.md` file that defines the skill's behavior.

**Example: Create a skills ConfigMap**

```bash
# Create a ConfigMap with skills
oc create configmap claude-skills \
  --from-file=code-review-skill=./skills/code-review/SKILL.md \
  --from-file=security-audit-skill=./skills/security-audit/SKILL.md
```

The deployment manifests include an `items` projection in the skills volume that maps ConfigMap keys to subdirectory paths. When adding skills, update both the ConfigMap and the volume spec's `items` entries to match. For multi-skill setups, consider using a PVC instead of a ConfigMap.

### MCP Server Configuration

MCP (Model Context Protocol) servers extend Claude Code with additional tools. MCP servers can be configured via mounted config file or environment variable.

**Config file format:**

```json
{
  "mcpServers": {
    "remote-api": {
      "type": "http",
      "url": "https://mcp.example.com/v1",
      "headers": {
        "Authorization": "Bearer ${API_TOKEN}"
      }
    },
    "local-tool": {
      "command": "/usr/bin/my-tool",
      "args": ["--flag"],
      "env": {
        "TOOL_CONFIG": "/etc/tool.conf"
      }
    }
  }
}
```

**Common MCP server examples:**

GitHub (official remote MCP server, requires a [Personal Access Token](https://github.com/settings/tokens)). The `${GITHUB_PAT}` variable is expanded at runtime from the container's environment; inject it via a Kubernetes Secret (see "Injecting secrets" below):

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${GITHUB_PAT}"
      }
    }
  }
}
```

**Injecting secrets:** Environment variables like `${API_TOKEN}` can be injected via Kubernetes Secrets in the Deployment env section:

```yaml
env:
  - name: API_TOKEN
    valueFrom:
      secretKeyRef:
        name: mcp-credentials
        key: token
```

Avoid hardcoding credentials directly in the ConfigMap JSON.

**Transport types:**

| Type | Use case | Requirements |
|------|----------|--------------|
| `http` | Remote MCP servers (recommended) | Network access to endpoint |
| `sse` | Legacy remote servers | Network access to endpoint |
| `command` | Local process-based servers | Executable must exist in container |

**Note**: The base image includes `git`, `curl`, `jq`, `bash`, and `python3`. Command-based MCP servers requiring `npx` or other runtimes will not work unless you extend the image (see [Extending the Container Image](#extending-the-container-image)).

**Option 1: Mounted config file**

The deployment manifests mount a ConfigMap to `/etc/mcp/config.json`. Update the ConfigMap (name varies by deployment option: `claude-mcp-config`, `claude-vertex-mcp-config`, `claude-vllm-mcp-config`, or `claude-ogx-vllm-mcp-config`):

```bash
oc patch configmap claude-mcp-config -p '{
  "data": {
    "config.json": "{\"mcpServers\":{\"my-api\":{\"type\":\"http\",\"url\":\"https://mcp.example.com/v1\"}}}"
  }
}'
```

Then restart the deployment to pick up changes (use the appropriate deployment name):

```bash
oc rollout restart deployment/claude-code
```

**Option 2: Environment variable**

Set `MCP_CONFIG_JSON` with inline JSON in the Deployment spec:

```yaml
- name: MCP_CONFIG_JSON
  value: '{"mcpServers":{"my-api":{"type":"http","url":"https://mcp.example.com/v1"}}}'
```

### Workspace Instructions (CLAUDE.md)

You can inject workspace-specific instructions at deploy time by mounting a `CLAUDE.md` file to the `/workspace` directory:

```bash
# Create ConfigMap with CLAUDE.md
oc create configmap claude-workspace-instructions \
  --from-file=CLAUDE.md=./CLAUDE.md

# Add to deployment (volumeMounts section):
- name: workspace-instructions
  mountPath: /workspace/CLAUDE.md
  subPath: CLAUDE.md
  readOnly: true

# Add to deployment (volumes section):
- name: workspace-instructions
  configMap:
    name: claude-workspace-instructions
```

Claude Code automatically reads CLAUDE.md from the working directory and applies the instructions to the session.

### Overriding settings.json

All deployment manifests include a settings ConfigMap that mounts to `/workspace/.claude/settings.json` (accessible via `~/.claude/settings.json` symlink). The ConfigMap name varies by deployment option (`claude-settings`, `claude-vertex-settings`, `claude-vllm-settings`, or `claude-ogx-vllm-settings`). The default is empty (`{}`), which you can customize at deploy time:

```bash
# Update the settings ConfigMap (use the appropriate name for your deployment)
oc patch configmap claude-settings -p '{
  "data": {
    "settings.json": "{\n  \"model\": \"your-model-id\"\n}"
  }
}'

# Restart to apply (use the appropriate deployment name)
oc rollout restart deployment/claude-code
```

Or edit the ConfigMap directly in the deployment YAML before applying:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: claude-settings
data:
  settings.json: |
    {
      "model": "your-model-id"
    }
```

### Extending the Container Image

The base image includes `git`, `curl`, `jq`, `bash`, and `python3`, which is sufficient for basic tasks. For real coding workflows, you will likely need additional language runtimes and tools so the agent can run tests, lint code, and build projects. Including the runtimes your project uses significantly improves agent output quality since the agent can run tests and catch its own mistakes.

The following example adds common development tools. Remove any you don't need:

```dockerfile
# In the "Install System Dependencies" section of the Containerfile
RUN microdnf install -y --nodocs \
        git \
        curl \
        jq \
        python3.12 \
        python3.12-pip \
        # Build tools
        make \
        gcc \
        tar \
        unzip \
        patch \
        diffutils \
        which \
        # Node.js (includes npm)
        nodejs \
        # Go
        golang \
        # Java
        java-21-openjdk-devel \
        maven \
        # Rust
        rust \
        cargo \
    && microdnf clean all \
    && rm -rf /var/cache/yum
```

The GitHub CLI (`gh`) is not available in UBI repos and must be installed separately:

```dockerfile
# Install GitHub CLI
ARG GH_VERSION=2.74.1
RUN curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin --strip-components=2 "gh_${GH_VERSION}_linux_amd64/bin/gh"
```

---

## Cleanup

### Option A: Anthropic API resources

```bash
oc delete deployment claude-code
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete secret claude-credentials
oc delete configmap claude-mcp-config
oc delete configmap claude-skills
oc delete configmap claude-settings
oc delete pvc claude-workspace
oc delete project my-claude-project
```

### Option B: Vertex AI resources

```bash
oc delete deployment claude-code-vertex
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete secret claude-vertex-credentials
oc delete configmap claude-vertex-config
oc delete configmap claude-vertex-mcp-config
oc delete configmap claude-vertex-skills
oc delete configmap claude-vertex-settings
oc delete pvc claude-vertex-workspace
oc delete project my-claude-project
```

### Option C: vLLM (direct) resources

```bash
oc delete deployment claude-code-vllm
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete configmap claude-vllm-settings
oc delete configmap claude-vllm-mcp-config
oc delete configmap claude-vllm-skills
oc delete pvc claude-vllm-workspace
oc delete project my-claude-project
```

### Option D: vLLM via OGX resources

```bash
oc delete deployment claude-code-ogx-vllm
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete configmap claude-ogx-vllm-settings
oc delete configmap claude-ogx-vllm-mcp-config
oc delete configmap claude-ogx-vllm-skills
oc delete pvc claude-ogx-vllm-workspace
oc delete project my-claude-project
```
