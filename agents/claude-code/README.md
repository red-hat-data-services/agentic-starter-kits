# Claude Code on OpenShift

A guide to deploying Claude Code as a containerized agent on Red Hat OpenShift. Supports four backend configurations: Anthropic API, Google Vertex AI, vLLM direct, and vLLM via OGX gateway.

## Table of Contents

- [Licensing Notice](#licensing-notice)
- [Prerequisites](#prerequisites)
- [Step 1: Build the Container Image](#step-1-build-the-container-image)
- [Step 2: Create an OpenShift Project](#step-2-create-an-openshift-project)
- [Step 3: Choose Your Backend](#step-3-choose-your-backend)
  - [Option A: Anthropic API](#option-a-anthropic-api)
  - [Option B: Vertex AI](#option-b-vertex-ai)
  - [Option C: vLLM Direct](#option-c-vllm-direct)
  - [Option D: vLLM via OGX Gateway](#option-d-vllm-via-ogx-gateway)
- [Using Claude Code](#using-claude-code)
- [Configuration](#configuration)
- [MLflow Tracing (Optional)](#mlflow-tracing-optional)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)
- [Cleanup](#cleanup)
- [Known Limitations](#known-limitations)

---

## Licensing Notice

**Do not redistribute built container images.** The Containerfile installs Claude Code at build time via Anthropic's native installer. The resulting image contains Anthropic's proprietary binary, which is subject to their [commercial terms](https://code.claude.com/docs/en/legal-and-compliance) ("All rights reserved"). Building the image yourself for internal use is permitted, but redistributing the built image (e.g., pushing to a public registry) is not authorized.

---

## Prerequisites

- `podman` installed locally (on macOS, also run `podman machine init` and `podman machine start`)
- `oc` CLI installed and logged into your OpenShift cluster
- An Anthropic API key, a GCP service account key for Vertex AI, or a vLLM/OGX endpoint (no Anthropic credentials needed for self-hosted models)

All shell commands in this guide assume you are in the `deployment/` subdirectory, where the Containerfile and deployment manifests live:

```bash
cd deployment/
```

---

## Step 1: Build the Container Image

```bash
podman build -t claude-code:latest -f Containerfile .

# Build with a specific version
podman build --build-arg CLAUDE_CODE_VERSION=2.1.123 -t claude-code:2.1.123 -f Containerfile .
```

To verify the build locally, see the local test command in your chosen backend option below.

---

## Step 2: Create an OpenShift Project

```bash
oc new-project my-claude-project
```

---

## Step 3: Choose Your Backend

Follow **one** option below, then continue to [Using Claude Code](#using-claude-code).

| Option | Backend | Manifest | Deployment Name |
|--------|---------|----------|-----------------|
| [A](#option-a-anthropic-api) | Anthropic API | `deployment.yaml` | `claude-code` |
| [B](#option-b-vertex-ai) | Google Vertex AI | `deployment-vertex.yaml` | `claude-code-vertex` |
| [C](#option-c-vllm-direct) | vLLM Direct | `deployment-vllm.yaml` | `claude-code-vllm` |
| [D](#option-d-vllm-via-ogx-gateway) | vLLM via OGX | `deployment-ogx-vllm.yaml` | `claude-code-ogx-vllm` |

---

### Option A: Anthropic API

#### Get your API key

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Sign in or create an account
3. Navigate to **API Keys** and click **Create Key**
4. Copy the key (starts with `sk-ant-api03-...`)

You need a paid account with credits.

#### Local test (optional)

```bash
podman run --rm \
  -e ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE" \
  claude-code:latest \
  claude -p "What is 2+2?"
```

#### Deploy

```bash
# Create secret
oc create secret generic claude-credentials \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE"

# Apply manifest and build
oc apply -f deployment.yaml
oc start-build claude-code --from-dir=. --follow

# Wait and test
oc rollout status deployment/claude-code
oc exec deployment/claude-code -- bash -c '
  ~/.claude/claude-run -p "What is 2+2?"
'
```

---

### Option B: Vertex AI

#### Get your GCP credentials

You need a GCP service account with Vertex AI access.

**Option 1: GCP Console**

1. Go to [GCP Console](https://console.cloud.google.com)
2. Select your project (Vertex AI API must be enabled)
3. Navigate to **IAM & Admin > Service Accounts**
4. Click **+ CREATE SERVICE ACCOUNT**
   - Name: `claude-code-user`
   - Grant role: **Vertex AI User** (`roles/aiplatform.user`)
5. Click the service account > **Keys** tab
6. Click **Add Key > Create new key > JSON**
7. Save the downloaded key file

Creating service accounts requires **IAM Admin** or **Service Account Admin** permissions.

**Option 2: gcloud CLI**

```bash
gcloud iam service-accounts create claude-code-user \
  --display-name="Claude Code User"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:claude-code-user@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud iam service-accounts keys create ~/claude-vertex-key.json \
  --iam-account=claude-code-user@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

**Alternative: Application Default Credentials (ADC)**

If you already have credentials via `gcloud auth application-default login`, you can use your ADC file (typically at `~/.config/gcloud/application_default_credentials.json`) in place of a service account key. ADC credentials are user-scoped and typically carry broader permissions. Use ADC for local development only; for shared clusters, create a dedicated service account.

#### Local test (optional)

```bash
podman run --rm \
  -e CLAUDE_CODE_USE_VERTEX=1 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id" \
  -e CLOUD_ML_REGION="global" \
  -e GOOGLE_APPLICATION_CREDENTIALS="/var/secrets/google/key.json" \
  -v /path/to/your-service-account-key.json:/var/secrets/google/key.json:ro,z \
  claude-code:latest \
  claude -p "What is 2+2?"
```

#### Deploy

```bash
# Create secret
oc create secret generic claude-vertex-credentials \
  --from-file=key.json=/path/to/your-service-account-key.json

# Apply manifest
oc apply -f deployment-vertex.yaml

# Patch ConfigMap with your project details
oc patch configmap claude-vertex-config \
  -p '{"data":{"ANTHROPIC_VERTEX_PROJECT_ID":"your-gcp-project-id","CLOUD_ML_REGION":"global"}}'

# Build and deploy
oc start-build claude-code --from-dir=. --follow
oc rollout restart deployment/claude-code-vertex
oc rollout status deployment/claude-code-vertex

# Test
oc exec deployment/claude-code-vertex -- bash -c '
  ~/.claude/claude-run -p "What is 2+2?"
'
```

**Model selection:** On Vertex AI, the default `sonnet` model alias may resolve to an older model than on the direct Anthropic API. To use a specific version:

```bash
oc set env deployment/claude-code-vertex CLAUDE_MODEL=claude-sonnet-4-6
```

---

### Option C: vLLM Direct

Connects Claude Code directly to a vLLM server's `/v1/messages` endpoint.

```text
Claude Code pod  ──HTTP──>  vLLM server (/v1/messages)
```

#### Prerequisites

- A vLLM server with `/v1/messages` endpoint support. If you need to deploy one, see [vllm/README.md](vllm/README.md).
- **Context window**: minimum 32K tokens (Claude Code's system prompt is ~23K). For realistic coding work, **128K+ is strongly recommended** since CLAUDE.md, skills, file listings, and conversation easily push past 100K tokens.
- Network connectivity from your OpenShift cluster to the vLLM server. See [Network Connectivity](#network-connectivity-vllmogx) in Troubleshooting if the server is outside the cluster.

**Model quality note:** Claude Code is designed for Anthropic's Claude models. Open source models may produce lower quality results, particularly for complex multi-step tasks. Including language runtimes in the container (see [Extending the Container Image](#extending-the-container-image)) helps because the agent can run tests and catch its own mistakes.

#### Edit the deployment manifest

Edit `deployment-vllm.yaml`. Search for placeholder values and replace them:

- `ANTHROPIC_BASE_URL`: Your vLLM server's base URL, for example:
  - `http://my-vllm-service.namespace.svc.cluster.local` (cluster-internal)
  - `https://vllm.apps.cluster.example.com` (external route)

Replace model IDs in the **ConfigMap** and the **Deployment** env vars. If your vLLM server hosts only one model, use the same model ID everywhere. If it hosts multiple models, you can assign different models to each role (e.g., a small fast model for haiku, a mid-range model for sonnet, and your most capable model for opus).

| Variable | Purpose | Example (single model) |
|----------|---------|----------------------|
| ConfigMap `"model"` | Default model in `settings.json` | `gpt-oss-120b` |
| `CLAUDE_MODEL` | Main conversation model (overrides ConfigMap) | `gpt-oss-120b` |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` | Adds model to the interactive mode picker menu | `gpt-oss-120b` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | What the `haiku` alias resolves to (used for background tasks like summarization) | `gpt-oss-120b` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | What the `sonnet` alias resolves to (selectable via `/model sonnet`) | `gpt-oss-120b` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | What the `opus` alias resolves to (selectable via `/model opus`, used for plan mode) | `gpt-oss-120b` |

The three alias overrides are required. Without them, Claude Code tries to resolve haiku, sonnet, and opus to Anthropic model names (e.g., `claude-haiku-4-5-20251001`), which don't exist on vLLM, causing 404 errors.

#### Context window configuration

Claude Code defaults to a 180K context window, which causes failures on models with smaller windows. Configure these env vars in the deployment manifest:

- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`: Your model's context window in tokens (e.g., `131072`). Do not pre-subtract output tokens.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS`: Output budget (e.g., `28000`).
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`: Autocompaction threshold. Formula: `percentage <= (context_window - max_output_tokens) / context_window * 100`

| Model | Context | AUTO_COMPACT_WINDOW | MAX_OUTPUT_TOKENS | AUTOCOMPACT_PCT |
|-------|---------|--------------------|--------------------|-----------------|
| *(32K minimum example)* | 32K | 32768 | 4000 | 85 |
| RedHatAI/Qwen3.6-35B-A3B-NVFP4 | 131K | 131072 | 28000 | 75 |
| Qwen/Qwen3-235B-A22B | 131K | 131072 | 28000 | 75 |
| openai/gpt-oss-120b | 131K | 131072 | 28000 | 75 |
| ibm-granite/granite-4.1-8b-instruct | 524K | 524288 | 64000 | 83 |
| meta-llama/Llama-4-Maverick-17B-128E | 1,048K | 1048576 | 64000 | 83 |

Models with 500K+ context can use the default 83% threshold. Models with smaller context windows need a lower percentage to leave sufficient headroom for output tokens. A 32K model is the minimum supported; expect frequent autocompaction and limited conversation depth at this size.

#### Local test (optional)

```bash
podman run --rm \
  -e ANTHROPIC_BASE_URL="https://YOUR_VLLM_ENDPOINT" \
  -e ANTHROPIC_AUTH_TOKEN="fake" \
  claude-code:latest \
  claude --model YOUR_MODEL_ID -p "What is 2+2?"
```

#### Deploy

```bash
oc apply -f deployment-vllm.yaml
oc start-build claude-code --from-dir=. --follow
oc rollout status deployment/claude-code-vllm

oc exec deployment/claude-code-vllm -- bash -c '
  ~/.claude/claude-run -p "What is 2+2?"
'
```

---

### Option D: vLLM via OGX Gateway

Uses OGX (from RHOAI) as an API gateway between Claude Code and vLLM.

```text
Claude Code pod  ──HTTP──>  OGX (API Gateway)  ──HTTP──>  vLLM server
```

#### Prerequisites

- OGX deployed and serving `GET /v1/health`, `GET /v1/models`, and `POST /v1/messages`. See [`ogx/README.md`](ogx/README.md) for one standalone deployment pattern, or reuse an existing OGX endpoint in your cluster.
- A vLLM server accessible from OGX.
- **Context window**: minimum 32K tokens. **128K+ strongly recommended** for realistic coding work.

**Model quality note:** Claude Code is designed for Anthropic's Claude models. Open source models may produce lower quality results, particularly for complex multi-step tasks. Including language runtimes in the container (see [Extending the Container Image](#extending-the-container-image)) helps because the agent can run tests and catch its own mistakes.

#### Edit the deployment manifest

Edit `deployment-ogx-vllm.yaml`. Search for placeholder values and replace them:

- `ANTHROPIC_BASE_URL`: Your OGX route URL (replace `YOUR_OGX_URL`)

Replace model IDs in the **ConfigMap** and the **Deployment** env vars. OGX uses the `vllm/` prefix to route requests to the vLLM backend, so all model IDs must use the exact `vllm/<model-id>` value returned by `GET /v1/models`. If OGX serves only one model, use the same value everywhere. If it serves multiple models, you can assign different models to each role.

| Variable | Purpose | Example (single model) |
|----------|---------|----------------------|
| ConfigMap `"model"` | Default model in `settings.json` | `vllm/gpt-oss-120b` |
| `CLAUDE_MODEL` | Main conversation model (overrides ConfigMap) | `vllm/gpt-oss-120b` |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` | Adds model to the interactive mode picker menu | `vllm/gpt-oss-120b` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | What the `haiku` alias resolves to (used for background tasks like summarization) | `vllm/gpt-oss-120b` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | What the `sonnet` alias resolves to (selectable via `/model sonnet`) | `vllm/gpt-oss-120b` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | What the `opus` alias resolves to (selectable via `/model opus`, used for plan mode) | `vllm/gpt-oss-120b` |

The three alias overrides are required. Without them, Claude Code tries to resolve haiku, sonnet, and opus to Anthropic model names, causing 404 errors.

#### Deploy

```bash
oc apply -f deployment-ogx-vllm.yaml
oc start-build claude-code --from-dir=. --follow
oc rollout status deployment/claude-code-ogx-vllm

oc exec deployment/claude-code-ogx-vllm -- bash -c '
  ~/.claude/claude-run -p "What is 2+2?"
'
```

---

## Using Claude Code

The examples below use `claude-code` as the deployment name. Substitute the name from the [backend table](#step-3-choose-your-backend) if you chose a different option.

### Running Prompts

The `claude-run` wrapper includes all container-configured arguments (permission bypass, MCP config, model selection):

```bash
oc exec deployment/claude-code -- bash -c '
  ~/.claude/claude-run -p "Your prompt here"
'
```

You can also source the environment directly:

```bash
oc exec deployment/claude-code -- bash -c '
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS -p "Your prompt here"
'
```

### Interactive Mode

For multi-turn conversations with a TTY:

```bash
# OpenShift
oc exec -it deployment/claude-code -- bash -c '
  ~/.claude/claude-run
'

# Local (example with Anthropic API; substitute env vars for your backend)
podman run -it --rm \
  -e ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE" \
  -v $(pwd):/workspace:z \
  claude-code:latest \
  claude
```

Interactive mode requires the `-it` flags for both `podman` and `oc exec`.

### Debug Mode

```bash
# Full debug logging
oc exec -it deployment/claude-code -- bash -c 'claude --debug'

# API calls only
oc exec -it deployment/claude-code -- bash -c 'claude --debug api'
```

Debug logs are written to a file. To tail them in real time from a second terminal:

```bash
oc exec deployment/claude-code -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

### Retrieving Files from the Container

When Claude Code generates files (reports, documents, code) that you want locally without pushing to Git, use `oc cp`:

```bash
# Copy a single file
oc cp <pod-name>:/workspace/projects/report.md ./report.md

# Copy a directory
oc cp <pod-name>:/workspace/projects/output/ ./output/

# Find the pod name
oc get pods -l app=claude-code -o name

# List files in the container
oc exec deployment/claude-code -- ls -la /workspace/projects/
```

### Rebuilding the Image

After modifying the Containerfile or entrypoint, rebuild and update the deployment:

```bash
# Build and push the new image
oc start-build claude-code --from-dir=. --follow

# Update the deployment to use the new image
oc set image deployment/<your-deployment-name> \
  claude-code=$(oc get istag claude-code:latest -o jsonpath='{.image.dockerImageReference}')
```

`oc rollout restart` alone is not sufficient. OpenShift pins deployments to a specific image digest, so restarting just recreates the pod with the old image. You must update the image reference with `oc set image` to pick up the new build.

---

## Configuration

### Session Persistence

Session history and memory persist across pod restarts via the workspace PVC. The `CLAUDE_CONFIG_DIR` environment variable points to `/workspace/.claude/`.

**Directory structure:**

```text
/workspace/                      <- PVC mount (persistent)
|-- .claude/                     <- Global config (CLAUDE_CONFIG_DIR)
|   |-- settings.json            <- Copied from ConfigMap at startup
|   |-- skills/                  <- ConfigMap mount
|   |-- memory/                  <- Persisted (global memory)
|   +-- projects/                <- Persisted (session history)
+-- projects/                    <- Working directory (where users run Claude)
    +-- .claude/                 <- Local auto-memory (separate from global)
```

This structure separates global config (`/workspace/.claude/`) from local auto-memory (`/workspace/projects/.claude/`), mirroring the experience of running Claude Code locally.

**What persists:**

| Data | Location | Persisted? |
|------|----------|------------|
| Session history | `/workspace/.claude/projects/` | Yes |
| Global memory | `/workspace/.claude/memory/` | Yes |
| Local auto-memory | `/workspace/projects/.claude/` | Yes |
| Project files | `/workspace/projects/` | Yes |
| Skills | `/etc/claude-skills/` (symlinked to `$CLAUDE_CONFIG_DIR/skills/`) | ConfigMap (re-mounted each restart) |
| Settings | `${CLAUDE_CONFIG_DIR}/settings.json` | Copied from ConfigMap on first start |

The entrypoint creates a symlink `~/.claude` -> `/workspace/.claude/` so that standard `~/.claude/` paths work as expected.

**Disabling persistence:** Set `CLAUDE_CONFIG_DIR` to a non-PVC path:

```yaml
env:
  - name: CLAUDE_CONFIG_DIR
    value: "/tmp/.claude"
```

### Injecting Skills

Skills extend Claude Code with custom instructions. They are auto-discovered from `~/.claude/skills/`. The skills ConfigMap is mounted at `/etc/claude-skills/` and the entrypoint symlinks it into `$CLAUDE_CONFIG_DIR/skills/`. Each skill must be in a subdirectory containing a `SKILL.md` file.

**Upgrading from older deployments:** If your PVC has an existing `skills/` directory from a previous deployment, the entrypoint automatically moves it to `skills.bak/` before creating the symlink.

**1. Create a SKILL.md file:**

```markdown
# Code Review

When reviewing code, analyze for:

1. **Correctness** - Logic errors, edge cases, off-by-one errors
2. **Security** - Input validation, injection risks, hardcoded secrets
3. **Performance** - Unnecessary loops, N+1 queries, missing indexes

Provide feedback as:
- **Must Fix** - Bugs or security issues
- **Should Fix** - Performance or maintainability concerns
- **Consider** - Style suggestions or minor improvements
```

**2. Create a ConfigMap from your skill files:**

```bash
oc create configmap <skills-configmap-name> \
  --from-file=code-review-skill=./skills/code-review/SKILL.md
```

The ConfigMap name must match your deployment manifest (e.g., `claude-skills`, `claude-vllm-skills`).

**3. Add an `items` mapping to the skills volume in your deployment manifest:**

The `items` mapping is required so Kubernetes creates the `<skill-name>/SKILL.md` subdirectory structure that Claude Code expects. Without it, the file appears as a flat file and won't be discovered.

```yaml
volumes:
  - name: skills
    configMap:
      name: <skills-configmap-name>
      optional: true
      items:
        - key: code-review-skill
          path: code-review/SKILL.md
```

Each `items` entry maps a ConfigMap key to a path under the mount point. For multiple skills, add one entry per skill. For many skills, consider a PVC instead of a ConfigMap.

### MCP Server Configuration

MCP (Model Context Protocol) servers extend Claude Code with additional tools. Configure via mounted config file or environment variable.

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

**GitHub MCP example** (requires a [Personal Access Token](https://github.com/settings/tokens)). The `${GITHUB_PAT}` variable is expanded at runtime from the container's environment; inject it via a Kubernetes Secret (see below):

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

Avoid hardcoding credentials in ConfigMap JSON.

**Transport types:**

| Type | Use case | Requirements |
|------|----------|--------------|
| `http` | Remote MCP servers (recommended) | Network access to endpoint |
| `sse` | Legacy remote servers | Network access to endpoint |
| `command` | Local process-based servers | Executable must exist in container |

The base image includes `git`, `curl`, `jq`, `bash`, and `python3`. Command-based MCP servers requiring `npx` or other runtimes need a custom image (see [Extending the Container Image](#extending-the-container-image)).

**Option 1: Mounted config file.** The manifests mount a ConfigMap to `/etc/mcp/config.json`. Update the ConfigMap (name varies by deployment: `claude-mcp-config`, `claude-vertex-mcp-config`, `claude-vllm-mcp-config`, or `claude-ogx-vllm-mcp-config`):

```bash
oc patch configmap claude-mcp-config -p '{
  "data": {
    "config.json": "{\"mcpServers\":{\"my-api\":{\"type\":\"http\",\"url\":\"https://mcp.example.com/v1\"}}}"
  }
}'
oc rollout restart deployment/claude-code
```

**Option 2: Environment variable.** Set `MCP_CONFIG_JSON` with inline JSON in the Deployment spec:

```yaml
- name: MCP_CONFIG_JSON
  value: '{"mcpServers":{"my-api":{"type":"http","url":"https://mcp.example.com/v1"}}}'
```

### Workspace Instructions (CLAUDE.md)

Mount a `CLAUDE.md` file to the workspace directory to inject project-specific instructions:

```bash
oc create configmap claude-workspace-instructions \
  --from-file=CLAUDE.md=./CLAUDE.md
```

Add to the deployment manifest:

```yaml
# volumeMounts section:
- name: workspace-instructions
  mountPath: /workspace/CLAUDE.md
  subPath: CLAUDE.md
  readOnly: true

# volumes section:
- name: workspace-instructions
  configMap:
    name: claude-workspace-instructions
```

Claude Code automatically reads CLAUDE.md from the working directory and applies the instructions to the session.

### Overriding settings.json

All manifests include a settings ConfigMap staged at a read-only path (`/etc/claude-config/settings.json`). On first start, the entrypoint copies it to `${CLAUDE_CONFIG_DIR}/settings.json` on the writable PVC. On subsequent restarts, the existing file is preserved so that runtime changes (e.g., hooks added by `mlflow autolog`) survive. To force a settings reset, delete the file from the PVC before restarting. The ConfigMap name varies by deployment (`claude-settings`, `claude-vertex-settings`, `claude-vllm-settings`, or `claude-ogx-vllm-settings`):

```bash
oc patch configmap claude-settings -p '{
  "data": {
    "settings.json": "{\n  \"model\": \"your-model-id\"\n}"
  }
}'
oc rollout restart deployment/claude-code
```

Or edit the ConfigMap in the manifest YAML before applying:

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

The base image includes `git`, `curl`, `jq`, `bash`, and `python3`. For real coding workflows, add language runtimes so the agent can run tests, lint, and build. Including the runtimes your project uses significantly improves agent output quality since the agent can run tests and catch its own mistakes.

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

## MLflow Tracing (Optional)

The container image includes MLflow 3.12 with the `kubernetes-namespaced` auth plugin, and the entrypoint automatically configures tracing when `MLFLOW_TRACKING_URI` is set. No changes to the Containerfile or entrypoint are needed.

### Prerequisites

- An MLflow instance running on your RHOAI cluster with a workspace matching your namespace.

### 1. Grant RBAC

```bash
oc adm policy add-role-to-user edit -z default -n <your-namespace>
```

For production, use a dedicated service account with least-privilege RBAC scoped to the permissions MLflow's `kubernetes-namespaced` auth plugin requires.

### 2. Add MLflow env vars to your deployment manifest

Uncomment the MLflow env vars in your deployment manifest (all four manifests include commented-out placeholders), or add these to the `env` section:

```yaml
- name: MLFLOW_TRACKING_URI
  value: "https://mlflow.<rhoai-namespace>.svc:8443/mlflow"
- name: MLFLOW_TRACKING_AUTH
  value: "kubernetes-namespaced"
- name: MLFLOW_WORKSPACE
  value: "<your-namespace>"
- name: MLFLOW_EXPERIMENT_NAME
  value: "claude-code-traces"
- name: MLFLOW_TRACKING_INSECURE_TLS
  value: "true"  # dev/test only; production should use proper TLS certificates
```

The `<rhoai-namespace>` is commonly `redhat-ods-applications`. The `/mlflow` path suffix is required for MLflow 3.12+.

If your deployment is already running, re-apply the manifest and restart the pod to pick up the new env vars:

```bash
oc apply -f <your-deployment-manifest>.yaml
oc rollout restart deployment/<deployment-name>
```

### 3. Verify

```bash
# Check startup logs for MLflow initialization
oc logs deployment/<deployment-name> | grep -i mlflow

# Run a test prompt
oc exec deployment/<deployment-name> -- bash -c '
  ~/.claude/claude-run -p "What is 2+2?"
'

# Check your MLflow UI for a new trace under the experiment name
```

### 4. View traces in the MLflow UI

Find the MLflow UI URL from the ConsoleLink:

```bash
oc get consolelink mlflow -o jsonpath='{.spec.href}'
```

This typically returns a URL through the RHOAI data science gateway (e.g., `https://rh-ai.<cluster-domain>/mlflow`). Open that URL in your browser and log in with the same OpenShift identity that deployed the agent. The MLflow workspace maps to the Kubernetes namespace, so you must have RBAC access to the agent's namespace to see its experiments and traces.

After login, select your workspace (the namespace name, e.g., `my-claude-code`) and navigate to the experiment you configured in `MLFLOW_EXPERIMENT_NAME`.

> **Note:** The direct MLflow route (`mlflow-<rhoai-namespace>.<cluster-domain>`) does not handle browser authentication. Always use the gateway URL from the ConsoleLink, which routes through OAuth.

### What gets traced

Each session captures tool call sequences, token counts (input/output/total), session duration, model name, and status as OTel spans. The stop-hook fires after the session ends, so there is zero impact on agent response times. The trace schema works identically across all four backends.

### MLflow version options

The default Containerfile uses MLflow 3.12 with a Python hook. MLflow 3.14+ also supports an npm plugin approach — uncomment the npm plugin env var in your deployment manifest to enable it. The plugin must be built from [upstream master](https://github.com/mlflow/mlflow/tree/master/libs/typescript) until the next plugin release syncs the fix. See [mlflow-tracing.md](mlflow-tracing.md) for a comparison of both approaches.

> **TLS note:** The npm plugin currently requires `NODE_TLS_REJECT_UNAUTHORIZED=0` or `NODE_EXTRA_CA_CERTS` for clusters with non-public TLS certificates. Both are process-wide Node.js settings. Upstream work is in progress to support `MLFLOW_TRACKING_INSECURE_TLS` and `MLFLOW_TRACKING_SERVER_CERT_PATH` scoped to MLflow connections only ([mlflow#24140](https://github.com/mlflow/mlflow/issues/24140)). Kubernetes-native auth (`MLFLOW_TRACKING_AUTH`) is also being added to the TypeScript SDK ([mlflow#24141](https://github.com/mlflow/mlflow/issues/24141)).

For detailed tracing investigation results and benchmark data, see [mlflow-tracing.md](mlflow-tracing.md).

---

## Security Considerations

### SKIP_PERMISSIONS

The deployment manifests set `SKIP_PERMISSIONS=true` by default, passing `--dangerously-skip-permissions` to Claude Code. This disables all permission prompts, including file-system write confirmations and confirmation of destructive operations (e.g., `git push --force`).

**Why it's enabled by default:**

- The container runs as non-root with dropped capabilities and seccomp profiles
- Claude only has access to the isolated `/workspace` PVC, not host filesystems
- Permission prompts don't work well in non-interactive `oc exec` scenarios
- One of the main advantages of running Claude Code in an isolated container is enabling less-interrupted workflows

**Tradeoffs:** Running in an isolated container removes much of the reason you would normally keep permission checks in place: the container cannot access data that is not explicitly mounted into it. However, skipping permissions also disables guardrails against destructive operations on external services the agent can reach, such as force-pushing to a Git remote or making unintended API calls via MCP servers. If you are running interactively and want an extra layer of confirmation, you can disable `SKIP_PERMISSIONS`. But for headless or automated usage, permission prompts are not practical, and you should rely on the repository safeguards described below instead.

To disable, set `SKIP_PERMISSIONS=false` in the deployment manifest or remove the variable.

### Repository Safeguards

When an AI agent has push access to a Git repository, ensure the repository has protections against mistakes. This is especially important with `SKIP_PERMISSIONS=true` and when using less capable models that are more likely to make errors such as committing directly to main, force-pushing, or merging their own PRs.

**Recommended protections:**

- **Branch protection rules**: Protect your main/default branch so direct pushes are blocked, forcing all changes through pull requests. On GitHub: Settings > Branches > Branch protection rules.
- **Required pull request reviews**: Require at least one approval from someone other than the PR author before merging. This prevents the agent from opening and immediately merging a PR without human review.
- **Limit PAT scope**: When creating the GitHub Personal Access Token used by the agent, grant only the minimum permissions needed. See [GitHub's documentation on token scopes](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) for fine-grained token options.
- **Status checks**: Require CI checks (tests, linting) to pass before a PR can be merged, so broken code cannot be merged even if a review is approved.

These protections apply regardless of whether you are using Claude Code or any other AI coding tool. They are standard best practices for collaborative development, but become critical when an automated agent has commit and push access.

### Credential Isolation

When credentials such as GitHub PATs or API tokens are passed as environment variables or written to files inside the container, the agent can read them directly. This means the agent could inadvertently expose credentials in conversation output, commit messages, or through MCP server calls. This is a known limitation of the approach described in this guide.

For many use cases, this risk is acceptable when combined with the safeguards above: limiting PAT scope to the minimum required permissions, protecting branches, and requiring PR reviews. However, for environments with strict security requirements, the ideal approach is to isolate the agent from the credentials it depends on, so that it can use tools (like git push or GitHub APIs) without being able to see or exfiltrate the underlying secrets.

Container isolation solutions are actively exploring ways to provide this kind of separation. If credential isolation is a requirement for your deployment, consider evaluating such solutions as they mature.

---

## Troubleshooting

### Network Connectivity (vLLM/OGX)

If the vLLM or OGX server is outside the cluster (e.g., on EC2 or another cloud), verify the pod can reach it:

```bash
# Find the cluster's egress IP
oc exec deployment/claude-code-vllm -- curl -s ifconfig.me

# Test connectivity to the server
oc exec deployment/claude-code-vllm -- curl -s -o /dev/null -w "%{http_code}" http://YOUR_HOST:8000/v1/models
```

Common causes of connection failure include security group rules, network policies, and firewalls. If the server uses IP-based access rules, add the cluster egress IP to the allow list (e.g., AWS security group inbound rule on TCP port 8000).

### Context Window Errors

Models with insufficient context will fail with errors like:

```text
API Error: 400 {"type":"error","error":{"type":"BadRequestError",
"message":"max_tokens must be at least 1, got -7214."}}
```

This means the model's context window is too small to fit Claude Code's system prompt plus the requested output tokens. See [Context window configuration](#context-window-configuration) in Option C for how to configure the context window, autocompaction, and output budget.

### OGX 404 Logs

When monitoring OGX logs, some 404 responses are normal:

```bash
oc logs deployment/ogx --tail=50
```

```text
HEAD / 404        # Claude Code HTTP client probing
POST /v1/messages 404  # Initial probes (2x)
POST /v1/messages 200  # Successful request with "Using native /v1/messages passthrough"
```

The 404s are caused by Claude Code's HTTP client probing behavior and do not indicate errors. The key indicator of success is seeing `Using native /v1/messages passthrough` followed by a 200 response.

### Testing Endpoints Directly

To verify the vLLM or OGX server supports the Anthropic Messages API:

**vLLM:**

```bash
# Health and model listing
curl -s "https://YOUR_VLLM_ENDPOINT/health"
curl -s "https://YOUR_VLLM_ENDPOINT/v1/models"

# Non-streaming request
curl -s -X POST "https://YOUR_VLLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
  }'

# Streaming request
curl -s -X POST "https://YOUR_VLLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "max_tokens": 100,
    "stream": true,
    "messages": [{"role": "user", "content": "Say hello"}]
  }'

# Tool calling (Claude Code uses tools extensively)
curl -s -X POST "https://YOUR_VLLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "List files in the current directory"}],
    "tools": [{"name": "bash", "description": "Run a bash command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}]
  }'
```

**OGX:** Use the same commands with your OGX route URL and the `vllm/` model prefix reported by `GET /v1/models`:

```bash
OGX_URL=<your-ogx-route-host>
curl -s "https://$OGX_URL/v1/health"
curl -s "https://$OGX_URL/v1/models"

curl -s -X POST "https://$OGX_URL/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "vllm/YOUR_MODEL_ID",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
  }'
```

### Model Aliasing

vLLM supports model aliasing via `--served-model-name`, letting you serve a model under a custom name without OGX:

```yaml
command:
  - python3
  - -m
  - vllm.entrypoints.openai.api_server
  - --model
  - openai/gpt-oss-120b
  - --served-model-name
  - my-custom-model-name
```

Then set `CLAUDE_MODEL` on the Claude Code deployment to match:

```bash
oc set env deployment/claude-code CLAUDE_MODEL=my-custom-model-name
```

`--served-model-name` is a **replacement**, not an addition. The original HuggingFace model ID is no longer recognized after setting an alias. To keep both the original name and an alias, pass the flag twice: `--served-model-name openai/gpt-oss-120b --served-model-name my-alias`.

### Interactive Wizard API Key Confirmation

When launching interactive mode, Claude Code's setup wizard includes an API key confirmation page. The behavior depends on which authentication env var you use:

- **`ANTHROPIC_AUTH_TOKEN`**: The key confirmation page is skipped entirely. This is what the vLLM and OGX manifests use. Set it to `"fake"` if your backend requires no authentication, or to a real token if it does.
- **`ANTHROPIC_API_KEY`**: The wizard prompts you to accept or reject the key. Use this for the Anthropic API (Option A) or any backend that requires an Anthropic-style API key. You must accept the key when prompted; see below for what happens if you reject it.

**If you reject an API key**, Claude Code stores the rejection in `/workspace/.claude/.claude.json` on the PVC and redirects you to browser-based authentication. Restarting the pod does not help because the rejection is persisted on the PVC. To recover, either fix the config file or delete the PVC and redeploy:

```bash
# Option 1: Fix the config file
oc exec deployment/<your-deployment-name> -- python3 -c '
import json
f = "/workspace/.claude/.claude.json"
with open(f) as fh:
    d = json.load(fh)
d["customApiKeyResponses"] = {"approved": [], "rejected": []}
with open(f, "w") as fh:
    json.dump(d, fh, indent=2)
print("Fixed: cleared key rejections")
'

# Option 2: Delete PVC and redeploy (full fresh start)
oc delete pvc <your-workspace-pvc>
oc rollout restart deployment/<your-deployment-name>
```

### Test Scripts

For automated validation of vLLM endpoints and Claude Code functionality, see the test scripts in [vllm/tests/](vllm/tests/). Full documentation is in [vllm/README.md](vllm/README.md).

---

## Cleanup

Resources to delete, by deployment option:

**Option A (Anthropic API):**

```bash
oc delete deployment claude-code
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete secret claude-credentials
oc delete configmap claude-mcp-config claude-skills claude-settings
oc delete pvc claude-workspace
oc delete project my-claude-project
```

**Option B (Vertex AI):**

```bash
oc delete deployment claude-code-vertex
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete secret claude-vertex-credentials
oc delete configmap claude-vertex-config claude-vertex-mcp-config claude-vertex-skills claude-vertex-settings
oc delete pvc claude-vertex-workspace
oc delete project my-claude-project
```

**Option C (vLLM direct):**

```bash
oc delete deployment claude-code-vllm
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete configmap claude-vllm-settings claude-vllm-mcp-config claude-vllm-skills
oc delete pvc claude-vllm-workspace
oc delete project my-claude-project
```

**Option D (OGX + vLLM):**

```bash
oc delete deployment claude-code-ogx-vllm
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete configmap claude-ogx-vllm-settings claude-ogx-vllm-mcp-config claude-ogx-vllm-skills
oc delete pvc claude-ogx-vllm-workspace
oc delete project my-claude-project
```

---

## Known Limitations

### Context Window Requirement

Claude Code sends a large internal system prompt (~23K tokens) with every request. Models with insufficient context will fail. Minimum: 32K tokens. Recommended: 128K+ for multi-turn conversations with tool use.

### Open Source Model Quality

Claude Code is designed and optimized for Anthropic's Claude models. Open source models may produce lower quality results, particularly for complex multi-step tasks, tool use chains, and code generation. Including language runtimes in the container helps because the agent can run tests and iterate on its own output.

### LLMInferenceService vs Standalone Deployment

The KServe `LLMInferenceService` CRD adds a `storage-initializer` init container that uses HF Xet for model downloads. This can stall on large models (60GB+) due to CDN timeouts, and the CRD does not expose init container env overrides. The standalone Deployment approach (used in [vllm/README.md](vllm/README.md)) lets vLLM download the model directly with standard HTTP, which is more reliable.

Use `LLMInferenceService` when you need the llm-d router/scheduler for multi-replica intelligent routing. Use standalone Deployment for single-replica setups or when the init container stalls.
