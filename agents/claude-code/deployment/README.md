# How to Deploy Claude Code on OpenShift

A step-by-step guide to build, test, and deploy the Claude Code container image.

## Licensing Notice

**Do not redistribute built container images.** The Containerfile installs Claude Code at build time via Anthropic's native installer. The resulting image contains Anthropic's proprietary binary, which is subject to their [commercial terms](https://code.claude.com/docs/en/legal-and-compliance) ("All rights reserved"). Building the image yourself for internal use is permitted, but redistributing the built image (e.g., pushing to a public registry) is not authorized.

## Prerequisites

- `podman` installed locally (on macOS, you also need to run `podman machine init` and `podman machine start` before building)
- `oc` CLI installed and logged into your OpenShift cluster
- An Anthropic API key OR a GCP service account key for Vertex AI
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
  cd /workspace
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
  cd /workspace
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
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
  cd /workspace
  ~/.claude/claude-run
'

# Alternative: source env.sh directly
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
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
  cd /workspace
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
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
- The vLLM model must have a **context window of at least 32K tokens** (Claude Code's system prompt is ~23K tokens)
- Network connectivity from your OpenShift cluster to the vLLM server

**Important**: Claude Code internally uses model aliases (haiku, sonnet, opus) for certain operations. When using vLLM, you must override these aliases using environment variables (see step 3 below), otherwise Claude Code will attempt to use Anthropic model names which will result in 404 errors.

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

### 4. Apply the deployment manifest

```bash
oc apply -f deployment-vllm.yaml
```

### 5. Build the image on OpenShift

```bash
oc start-build claude-code --from-dir=. --follow
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
  cd /workspace
  ~/.claude/claude-run
'
```

### 9. Debug mode

```bash
# Enable full debug logging
oc exec -it deployment/claude-code-vllm -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-vllm -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
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
- The vLLM model must have a **context window of at least 32K tokens** (Claude Code's system prompt is ~23K tokens)

**Important**: Claude Code internally uses model aliases (haiku, sonnet, opus) for certain operations. When using OGX with vLLM, you must override these aliases using environment variables (see step 1 below), otherwise Claude Code will attempt to use Anthropic model names which will result in 404 errors.

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
  cd /workspace
  ~/.claude/claude-run
'
```

### 8. Debug mode

```bash
# Enable full debug logging
oc exec -it deployment/claude-code-ogx-vllm -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-ogx-vllm -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
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

The deployment manifests set `SKIP_PERMISSIONS=true` by default, which passes `--dangerously-skip-permissions` to Claude Code. This disables all file-system write permission prompts.

**Why it's enabled by default:**

- The container runs as non-root with dropped capabilities and seccomp profiles
- Claude only has access to the isolated `/workspace` PVC, not host filesystems
- Permission prompts don't work well in non-interactive `oc exec` scenarios

**When to disable:**

- If you mount sensitive host directories into the container
- If you're running in a less isolated environment
- If you want Claude to prompt before file operations

To disable, set `SKIP_PERMISSIONS=false` in the deployment manifest or remove the environment variable entirely.

---

## Customization

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

**Mount path:** `/home/claude-agent/.claude/skills`

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

**Note**: The lean UBI base image only includes `git`, `curl`, `jq`, and `bash`. Command-based MCP servers requiring `npx`, `python`, or other runtimes will not work unless you extend the image.

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

All deployment manifests include a settings ConfigMap that mounts to `~/.claude/settings.json`. The ConfigMap name varies by deployment option (`claude-settings`, `claude-vertex-settings`, `claude-vllm-settings`, or `claude-ogx-vllm-settings`). The default is empty (`{}`), which you can customize at deploy time:

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
