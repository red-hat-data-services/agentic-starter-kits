# Codex on OpenShift

A guide to deploying [OpenAI Codex CLI](https://github.com/openai/codex) as a containerized coding agent on Red Hat OpenShift. Connects to a vLLM inference endpoint via the OpenAI Responses API (`/v1/responses`).

## Table of Contents

- [Licensing](#licensing)
- [Prerequisites](#prerequisites)
- [Step 1: Build the Container Image](#step-1-build-the-container-image)
- [Step 2: Create an OpenShift Project](#step-2-create-an-openshift-project)
- [Step 3: Deploy](#step-3-deploy)
- [Local Test (Optional)](#local-test-optional)
- [Using Codex](#using-codex)
  - [Interactive Mode](#interactive-mode)
  - [Headless Execution](#headless-execution)
  - [Retrieving Files from the Container](#retrieving-files-from-the-container)
- [Configuration](#configuration)
  - [Session Persistence](#session-persistence)
  - [config.toml Overrides](#configtoml-overrides)
  - [MCP Servers](#mcp-servers)
  - [Extending the Container Image](#extending-the-container-image)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)
- [Cleanup](#cleanup)
- [Known Limitations](#known-limitations)
- [OpenShell Sandbox](#openshell-sandbox)

---

## Licensing

Codex CLI is released under the [Apache 2.0 license](https://github.com/openai/codex/blob/main/LICENSE). The Containerfiles in this directory and the resulting images are freely redistributable. No proprietary components are included.

---

## Prerequisites

- `podman` installed locally (on macOS, also run `podman machine init` and `podman machine start`)
- `oc` CLI installed and logged into your OpenShift cluster
- A vLLM endpoint (upstream v0.25.1+) serving the OpenAI Responses API at `/v1/responses` with tool calling enabled (`--enable-auto-tool-choice --tool-call-parser <parser>`). **Important:** harmony models (gpt-oss) do not support namespace tools — use a non-harmony model. See [Responses API Compatibility](#responses-api-compatibility) for tested model/parser combinations.

Codex CLI uses the **Responses API exclusively**. It does not use the Chat Completions API (`/v1/chat/completions`). Your vLLM server must support `/v1/responses` and tool calling with namespace tool types.

All shell commands in this guide assume you are in the `deployment/` subdirectory, where the Containerfile and deployment manifests live:

```bash
cd deployment/
```

---

## Step 1: Build the Container Image

The Codex CLI binary installed in this image is a pre-built artifact published by OpenAI via npm (`@openai/codex`). It has not been built, scanned, or validated according to Red Hat standards. Use it at your own discretion. To build from source instead, see `Containerfile.base`.

```bash
podman build --platform linux/amd64 \
  -t codex:latest \
  -f Containerfile .

# Build with a specific version
podman build --platform linux/amd64 \
  --build-arg CODEX_VERSION=0.144.0 \
  -t codex:0.144.0 \
  -f Containerfile .
```

Always pass `--platform linux/amd64` when building on Apple Silicon — the npm package downloads a platform-specific binary, and x86_64 is required for OpenShift nodes.

### Version pinning

The `CODEX_VERSION` build arg controls which npm package version to install. It defaults to `0.144.0`. Available versions are listed at [github.com/openai/codex/releases](https://github.com/openai/codex/releases).

### Image size

| Image | Approximate Size | Contents |
|-------|-----------------|----------|
| `codex` | ~579 MB | UBI 9 minimal + Codex CLI (via npm) + git, jq, tar, nodejs, npm + entrypoint |

### Building from source (alternative)

For supply chain trust, `Containerfile.base` compiles Codex from the upstream Apache 2.0 source using the Rust toolchain. This produces an auditable binary with no pre-built artifacts. See the header comments in `Containerfile.base` for build instructions. Building from source requires 32 GB+ RAM in the podman VM for cross-compilation on Apple Silicon.

---

## Step 2: Create an OpenShift Project

```bash
oc new-project my-codex-project
```

---

## Step 3: Deploy

### Configure the vLLM endpoint

Edit `deployment.yaml` and update the placeholder values in the Deployment env section:

| Variable | Purpose | Example |
|----------|---------|---------|
| `OPENAI_BASE_URL` | vLLM server base URL (must serve `/v1/responses`) | `http://vllm-svc.namespace.svc.cluster.local/v1` |
| `OPENAI_API_KEY` | API key for the vLLM endpoint (use `"dummy"` if none required) | `dummy` |
| `OPENAI_MODEL` | Model ID as reported by `GET /v1/models` | `your-model-id` |

The entrypoint automatically generates a `[model_providers.vllm]` block in `config.toml` from these environment variables. You do not need to write TOML configuration manually for the basic case.

### Apply manifests and build

The deployment manifest contains all required resources: ImageStream, BuildConfig, ConfigMaps (config.toml and MCP), a 1Gi PVC, and the Deployment.

```bash
# Apply all resources (ImageStream, BuildConfig, ConfigMaps, PVC, Deployment)
oc apply -f deployment.yaml

# Build locally and push to the internal registry (recommended)
#
# Get the external registry route and login:
REGISTRY=$(oc get route -n openshift-image-registry -o jsonpath='{.items[0].spec.host}')
podman login "${REGISTRY}" -u $(oc whoami) -p $(oc whoami -t) --tls-verify=false
#
# Tag and push:
podman tag codex:latest "${REGISTRY}/$(oc project -q)/codex:latest"
podman push "${REGISTRY}/$(oc project -q)/codex:latest" --tls-verify=false
#
# Import into the ImageStream
oc tag --source=docker \
  image-registry.openshift-image-registry.svc:5000/$(oc project -q)/codex:latest \
  codex:latest

# Wait for rollout
oc rollout status deployment/codex
```

### Verify the deployment

```bash
# Check the pod is running and the entrypoint configured correctly
oc exec deployment/codex -- bash -c 'codex --version && cat ~/.codex/config.toml'

# Test connectivity to the vLLM endpoint
oc exec deployment/codex -- bash -c \
  'curl -s http://vllm-svc.your-namespace.svc.cluster.local/v1/models | jq .'
```

---

## Local Test (Optional)

Test the image locally with podman before deploying to OpenShift:

```bash
# Headless execution
podman run --rm \
  -e OPENAI_BASE_URL="http://YOUR_VLLM_ENDPOINT/v1" \
  -e OPENAI_API_KEY="dummy" \
  -e OPENAI_MODEL="YOUR_MODEL_ID" \
  codex:latest \
  codex exec "What is 2+2?"

# Interactive mode
podman run -it --rm \
  -e OPENAI_BASE_URL="http://YOUR_VLLM_ENDPOINT/v1" \
  -e OPENAI_API_KEY="dummy" \
  -e OPENAI_MODEL="YOUR_MODEL_ID" \
  -v $(pwd):/workspace/projects:z \
  codex:latest \
  codex
```

For interactive mode, both `-i` (stdin) and `-t` (tty) flags are required.

---

## Using Codex

The deployment runs `sleep infinity` so the pod stays alive for `oc exec` sessions. All examples below use `codex` as the deployment name.

### The codex-run Wrapper

The entrypoint generates a `codex-run` wrapper script at `~/.codex/codex-run` that includes all container-configured arguments (model, sandbox mode, provider config). Use it for all `oc exec` sessions. Use `bash -l` (login shell) so `.bashrc` adds `~/.codex` to PATH:

```bash
oc exec deployment/codex -- bash -lc '
  codex-run exec "Your prompt here"
'
```

You can also source the environment directly:

```bash
oc exec deployment/codex -- bash -c '
  source ~/.codex/env.sh
  codex ${CODEX_EXTRA_ARGS} exec "Your prompt here"
'
```

### Interactive Mode

For multi-turn conversations with a TTY:

```bash
oc exec -it deployment/codex -- bash -lc 'codex-run'
```

Interactive mode requires the `-it` flags on `oc exec`. Without them, the TUI will not render and Codex will exit immediately.

### Headless Execution

The `codex exec` subcommand runs a prompt non-interactively and exits when complete. This is the recommended mode for scripted or automated usage:

```bash
# Single prompt
oc exec deployment/codex -- bash -lc '
  codex-run exec "Explain the structure of this project"
'

# With a specific working directory
oc exec deployment/codex -- bash -lc '
  cd /workspace/projects/my-repo && codex-run exec "Run the tests and fix any failures"
'
```

`codex exec` requires `CODEX_API_KEY` to be set. The entrypoint automatically propagates `OPENAI_API_KEY` to `CODEX_API_KEY` if only the former is set.

### Retrieving Files from the Container

When Codex generates files (reports, patches, code) that you want locally without pushing to Git, use `oc cp`:

```bash
# Copy a single file
oc cp <pod-name>:/workspace/projects/report.md ./report.md

# Copy a directory
oc cp <pod-name>:/workspace/projects/output/ ./output/

# Find the pod name
oc get pods -l app=codex -o name

# List files in the container
oc exec deployment/codex -- ls -la /workspace/projects/
```

### Rebuilding the Image

After modifying the Containerfile or entrypoint, rebuild locally and push:

```bash
podman build --platform linux/amd64 -t codex:latest -f Containerfile .

REGISTRY=$(oc get route -n openshift-image-registry -o jsonpath='{.items[0].spec.host}')
podman login "${REGISTRY}" -u $(oc whoami) -p $(oc whoami -t) --tls-verify=false
podman tag codex:latest "${REGISTRY}/$(oc project -q)/codex:latest"
podman push "${REGISTRY}/$(oc project -q)/codex:latest" --tls-verify=false

oc import-image codex:latest --confirm
oc rollout restart deployment/codex
oc rollout status deployment/codex
```

---

## Configuration

### Session Persistence

Session history and configuration persist across pod restarts via the workspace PVC. The `CODEX_HOME` environment variable defaults to `/workspace/.codex`.

**Directory structure:**

```text
/workspace/                      <- PVC mount (persistent)
|-- .codex/                     <- Codex config (CODEX_HOME)
|   |-- config.toml             <- Model provider, MCP, preferences
|   |-- env.sh                  <- Generated env for oc exec sessions
|   |-- codex-run               <- Wrapper script
|   +-- instructions.md         <- Persisted project instructions
+-- projects/                   <- WORKDIR (where users run Codex)
```

The entrypoint creates a symlink `~/.codex` -> `/workspace/.codex` so that standard `~/.codex/` paths work as expected.

**What persists:**

| Data | Location | Persisted? |
|------|----------|------------|
| Configuration | `/workspace/.codex/config.toml` | Yes |
| Project instructions | `/workspace/.codex/instructions.md` | Yes |
| Working files | `/workspace/projects/` | Yes |
| Codex CLI args | `/workspace/.codex/env.sh` | Regenerated on each restart |
| Wrapper script | `/workspace/.codex/codex-run` | Regenerated on each restart |

**Disabling persistence:** Set `CODEX_HOME` to a non-PVC path:

```yaml
env:
  - name: CODEX_HOME
    value: "/tmp/.codex"
```

### config.toml Overrides

Codex CLI uses TOML configuration at `$CODEX_HOME/config.toml`. The deployment manifest includes a ConfigMap (`codex-config`) that is staged at `/etc/codex-config/config.toml`. On first start, the entrypoint copies it to `${CODEX_HOME}/config.toml` on the writable PVC. On subsequent restarts, the existing file is preserved so that runtime changes survive.

The entrypoint auto-generates model provider configuration from the `OPENAI_BASE_URL` and `OPENAI_MODEL` environment variables. Use the ConfigMap only for settings beyond what the entrypoint generates.

**Generated config.toml example** (produced by entrypoint.sh when `OPENAI_BASE_URL` and `OPENAI_MODEL` are set):

```toml
# Auto-configured by entrypoint.sh
model = "your-model-id"
model_supports_reasoning_summaries = false
model_provider = "vllm"

[model_providers.vllm]
name = "vLLM"
base_url = "http://vllm-svc.namespace.svc.cluster.local/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
supports_websockets = false
```

**Manual config.toml example** (for advanced setups, place in the ConfigMap):

```toml
model = "granite-3.3-8b-instruct"
model_provider = "my-provider"

[model_providers.my-provider]
name = "Custom Provider"
base_url = "https://inference.example.com/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
```

To update the ConfigMap after deployment:

```bash
oc patch configmap codex-config -p '{
  "data": {
    "config.toml": "model = \"my-model\"\nmodel_provider = \"vllm\"\n\n[model_providers.vllm]\nname = \"vLLM\"\nbase_url = \"http://my-vllm-endpoint/v1\"\nenv_key = \"OPENAI_API_KEY\"\nwire_api = \"responses\"\n"
  }
}'
```

To force a config reset (pick up ConfigMap changes), delete the file from the PVC before restarting:

```bash
oc exec deployment/codex -- rm /workspace/.codex/config.toml
oc rollout restart deployment/codex
```

### MCP Servers

MCP (Model Context Protocol) servers extend Codex with additional tools. Codex uses TOML-native MCP configuration with `[mcp_servers.*]` blocks in `config.toml`. The entrypoint supports three injection methods:

#### Method 1: Mounted ConfigMap (recommended)

The deployment manifest mounts a ConfigMap at `/etc/codex-mcp/mcp-servers.toml`. The entrypoint appends its contents to `config.toml` at startup if the file contains `[mcp_servers.*]` blocks.

**TOML format:**

```toml
[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"

[mcp_servers.local-tool]
command = "npx"
args = ["-y", "@some/mcp-server"]
```

Update the ConfigMap:

```bash
oc patch configmap codex-mcp-config -p '{
  "data": {
    "mcp-servers.toml": "[mcp_servers.my-api]\nurl = \"https://mcp.example.com/v1\"\n"
  }
}'
oc rollout restart deployment/codex
```

#### Method 2: TOML file path (MCP_CONFIG_TOML)

Point to a TOML file containing `[mcp_servers.*]` blocks. The entrypoint appends its contents to `config.toml`.

```yaml
env:
  - name: MCP_CONFIG_TOML
    value: "/etc/codex-mcp/mcp-servers.toml"
```

This is useful when you have a TOML file mounted from a Secret or other volume.

#### Method 3: Inline JSON (MCP_CONFIG_JSON)

For compatibility with the Claude Code `MCP_CONFIG_JSON` pattern, the entrypoint accepts inline JSON and converts it to TOML automatically using `jq`:

```yaml
env:
  - name: MCP_CONFIG_JSON
    value: '{"mcpServers":{"my-api":{"url":"https://mcp.example.com/v1"},"local-tool":{"command":"npx","args":["-y","@some/mcp-server"]}}}'
```

The JSON-to-TOML conversion supports `url`, `command`, and `args` fields. For MCP servers requiring environment variable references (e.g., `bearer_token_env_var`), use Method 1 or 2 with native TOML instead.

#### MCP server types

| Type | TOML field | Use case | Requirements |
|------|-----------|----------|--------------|
| Remote HTTP | `url` | Remote MCP servers | Network access to endpoint |
| Local process | `command` + `args` | Process-based MCP servers | Executable must exist in container |

The image includes `git`, `curl-minimal`, `jq`, `tar`, `nodejs`, and `npm`. Command-based MCP servers using `npx` work out of the box. For servers requiring other runtimes, see [Extending the Container Image](#extending-the-container-image).

### Extending the Container Image

The image includes `git`, `curl-minimal`, `jq`, `tar`, `nodejs`, `npm`, and `bash`. For real coding workflows, add language runtimes so the agent can run tests, lint, and build. Including the runtimes your project uses significantly improves agent output quality since the agent can run tests and catch its own mistakes.

```dockerfile
# In the "System dependencies" section of Containerfile
RUN microdnf install -y --nodocs \
        git \
        jq \
        tar \
        nodejs \
        npm \
        # Build tools
        make \
        gcc \
        diffutils \
        which \
        # Python
        python3.12 \
        python3.12-pip \
        # Go
        golang \
        # Java
        java-21-openjdk-devel \
        maven \
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

## Security Considerations

### Sandbox Mode

The deployment manifest sets `CODEX_SANDBOX=danger-full-access` by default, passing `--sandbox danger-full-access` to the Codex CLI. This disables Codex's built-in sandboxing (which uses bubblewrap on Linux).

**Why it is set this way:**

- The container itself is the isolation boundary, running as non-root (UID 1001) under OpenShift's restricted-v2 SCC
- The pod security context drops all capabilities and enforces `allowPrivilegeEscalation: false` with a `RuntimeDefault` seccomp profile
- Codex only has access to the isolated `/workspace` PVC, not host filesystems
- The bubblewrap sandbox inside a container-in-a-container creates unnecessary complexity and can conflict with OpenShift security policies

**Tradeoffs:** Running in an isolated container removes much of the reason you would normally keep Codex's built-in sandbox enabled. However, `danger-full-access` also means the agent has unrestricted access to external services it can reach via the network (e.g., Git remotes, MCP endpoints). Rely on repository safeguards (branch protection, required reviews, limited PAT scopes) to mitigate risks from automated operations.

To use a different sandbox mode:

```yaml
env:
  - name: CODEX_SANDBOX
    value: "read-only-fs"
```

### Credential Isolation

When credentials such as GitHub PATs or API keys are passed as environment variables, the agent can read them directly. This means the agent could inadvertently expose credentials in conversation output, commit messages, or through MCP server calls.

For many use cases, this risk is acceptable when combined with standard safeguards: limiting PAT scope to the minimum required permissions, protecting branches, and requiring PR reviews. For environments with strict security requirements, consider evaluating container isolation solutions that separate the agent from the credentials it depends on.

### Repository Safeguards

When an AI agent has push access to a Git repository, ensure the repository has protections against mistakes:

- **Branch protection rules**: Protect your main/default branch so direct pushes are blocked
- **Required pull request reviews**: Require at least one approval before merging
- **Limit PAT scope**: Grant only the minimum permissions needed
- **Status checks**: Require CI checks to pass before a PR can be merged

---

## Troubleshooting

### Responses API Compatibility

Codex CLI uses the OpenAI Responses API (`/v1/responses`), not the Chat Completions API (`/v1/chat/completions`). If you see errors like "404 Not Found" or "endpoint not found", verify your vLLM server supports the Responses API:

```bash
# Check if /v1/responses endpoint exists
curl -s -o /dev/null -w "%{http_code}" \
  -X POST "http://YOUR_VLLM_ENDPOINT/v1/responses" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "input": "What is 2+2?"
  }'
```

**Namespace tool type compatibility:**

Codex sends `namespace` tool types with every request. Whether vLLM accepts them depends on the **model architecture**, not the parser or vLLM version.

| Model | Parser | vLLM Version | Result |
|---|---|---|---|
| gpt-oss-120b | `openai` | RHOAI 3.5 EA (vLLM v0.21.0) | `"tool type namespace not supported"` |
| gpt-oss-120b | `openai` | Upstream v0.25.1 | `"tool type namespace not supported"` |
| gpt-oss-120b | `hermes` | Upstream v0.25.1 | `"tool type namespace not supported"` |
| Any model | any | RHOAI 3.5 EA (vLLM v0.21.0) | `"Unexpected message role"` — Codex sends `developer` role which this version doesn't support |
| Qwen3.6-27B | `qwen3_coder` | Upstream v0.25.1 | Works (full tool calling) |
| Qwen3-32B | `hermes` | Upstream v0.25.1 | Works (full tool calling) |
| Qwen3-8B | `qwen3_coder` | Upstream v0.25.1 | Namespace accepted, but no tool execution (8B too small) |

The `"tool type namespace not supported"` error is specific to **harmony models** (gpt-oss family / `GptOssForCausalLM` architecture). This is a known vLLM limitation — namespace tool types are supported for non-harmony (open-source) models but not yet implemented for harmony models. The error was observed on all tested vLLM versions (RHOAI 3.5 EA (vLLM v0.21.0), upstream v0.25.1) and parsers (`openai`, `hermes`). The same error occurs when using OGX as the inference provider. Tracked upstream: [vllm-project/vllm#49493](https://github.com/vllm-project/vllm/issues/49493).

**To use Codex with vLLM, use an open-source model with the correct parser:**

```bash
# Qwen3.6-27B (tested, full tool calling works)
vllm serve Qwen/Qwen3.6-27B \
  --trust-remote-code \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --mm-encoder-tp-mode data

# Qwen3-32B (use hermes parser, not qwen3_coder)
vllm serve Qwen/Qwen3-32B \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --reasoning-parser qwen3
```

See the [vLLM Codex integration docs](https://docs.vllm.ai/en/latest/serving/integrations/codex/) for the full list of supported models and parsers.

**Tool calling on vLLM with open-source models:**

Tool execution depends on the model and parser combination. The entrypoint sets `supports_websockets = false` and `model_supports_reasoning_summaries = false` in the provider config, which are required for vLLM backends.

| Model | Parser | Simple Prompts | Tool Execution | Notes |
|---|---|---|---|---|
| Qwen3.6-27B | `qwen3_coder` | Works | **Works** | Tested on upstream vLLM v0.25.1 — full tool calling including file creation and shell commands |
| Qwen3-32B | `hermes` | Works | **Works** | Tested on upstream vLLM v0.25.1 — `hermes` parser extracts `<tool_call>` tags correctly |
| Qwen3-32B | `qwen3_coder` | Works | No | `qwen3_coder` parser does not extract Qwen3-32B's `<tool_call>` format — use `hermes` instead |
| Qwen3-8B | `qwen3_coder` | Works | No | 8B is too small for reliable tool calling |
| OpenAI models (via OpenAI API) | — | Works | Works | Native Responses API |

**Parser selection matters:** Newer Qwen models (3.6+) work with `qwen3_coder`. Older Qwen3 models (32B, 8B) need `hermes`. Using the wrong parser results in tool calls emitted as text instead of structured function calls.

**vLLM version requirements:** Upstream vLLM v0.25.1+ is required. RHOAI vLLM 3.5 EA (v0.21.0) returns `"Unexpected message role"` because Codex sends `developer` role messages which that version doesn't support (fixed upstream in [PR #43590](https://github.com/vllm-project/vllm/pull/43590)). RHOAI 3.6 EA (expected to be based on v0.26+) should include this fix.

### Network Connectivity

If the vLLM server is outside the cluster (e.g., on EC2 or another cloud), verify the pod can reach it:

```bash
# Find the cluster's egress IP
oc exec deployment/codex -- curl -s ifconfig.me

# Test connectivity to the vLLM server
oc exec deployment/codex -- curl -s -o /dev/null -w "%{http_code}" \
  http://YOUR_HOST:8000/v1/models
```

Common causes of connection failure include security group rules, network policies, and firewalls. If the server uses IP-based access rules, add the cluster egress IP to the allow list.

### Testing Endpoints Directly

Verify the vLLM server is reachable and serving the expected model:

```bash
# Health check
curl -s "http://YOUR_VLLM_ENDPOINT/health"

# Model listing
curl -s "http://YOUR_VLLM_ENDPOINT/v1/models"

# Non-streaming Responses API request
curl -s -X POST "http://YOUR_VLLM_ENDPOINT/v1/responses" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "input": "What is 2+2? Reply with just the number."
  }'

# Streaming Responses API request
curl -s -X POST "http://YOUR_VLLM_ENDPOINT/v1/responses" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "YOUR_MODEL_ID",
    "input": "Say hello",
    "stream": true
  }'
```

### Config Debugging

To inspect the generated `config.toml` and verify model provider and MCP configuration:

```bash
# View the generated config
oc exec deployment/codex -- cat /workspace/.codex/config.toml

# View entrypoint logs
oc logs deployment/codex | grep "\[entrypoint\]"

# Check env.sh (generated CLI args and environment)
oc exec deployment/codex -- cat ~/.codex/env.sh

# Verify Codex version
oc exec deployment/codex -- codex --version
```

### CODEX_API_KEY Missing

`codex exec` (headless mode) requires `CODEX_API_KEY` to be set. The entrypoint automatically propagates `OPENAI_API_KEY` to `CODEX_API_KEY` if only the former is set. If you see authentication errors in headless mode, verify both are set:

```bash
oc exec deployment/codex -- bash -c 'echo "OPENAI_API_KEY=${OPENAI_API_KEY:+set}" && echo "CODEX_API_KEY=${CODEX_API_KEY:+set}"'
```

### Pod Restart Loop

If the pod enters a CrashLoopBackOff, check the entrypoint logs:

```bash
oc logs deployment/codex --previous
```

Common causes:

- `CODEX_HOME` directory not writable (PVC not mounted or permissions issue)
- Invalid TOML in ConfigMap (syntax error in config.toml or mcp-servers.toml)
- npm registry unreachable (Codex CLI downloaded from npm at build time)

---

## Cleanup

```bash
oc delete deployment codex
oc delete buildconfig codex 2>/dev/null
oc delete imagestream codex 2>/dev/null
oc delete configmap codex-config codex-mcp-config
oc delete pvc codex-workspace
oc delete project my-codex-project
```

---

## Known Limitations

### Responses API Only

Codex CLI uses the OpenAI Responses API (`/v1/responses`) exclusively. It does not support the Chat Completions API (`/v1/chat/completions`) or the Anthropic Messages API (`/v1/messages`). Codex sends `namespace` tool types with every request. Namespace tools are a known unsupported feature for harmony models (gpt-oss) in vLLM — use non-harmony models instead. Requires upstream vLLM v0.25.1+ (RHOAI 3.5 EA (vLLM v0.21.0) does not support the `developer` message role). See [Responses API Compatibility](#responses-api-compatibility) for details.

### Open-Source Model Tool Calling

Tool calling with open-source models works but requires the correct model + parser combination. Tested configurations:

- **Qwen3.6-27B + `qwen3_coder`**: Full tool calling (file creation, shell commands) — tested and working
- **Qwen3-32B + `hermes`**: Full tool calling — tested and working
- **Qwen3-32B + `qwen3_coder`**: Tool calls emitted as text, not parsed — use `hermes` instead
- **Qwen3-8B**: Too small for reliable agentic tool calling

See [Responses API Compatibility](#responses-api-compatibility) for the full compatibility table.

### No Built-in Permission System

Unlike Claude Code, Codex CLI does not have a granular permission system for file operations or shell commands. The `--sandbox` flag controls the sandbox mode, but `danger-full-access` grants unrestricted access within the container. Rely on OpenShift's container isolation and repository safeguards for security.

### TOML Configuration Only

Codex CLI uses TOML for all configuration (`config.toml`). There is no JSON settings file equivalent. The entrypoint's `MCP_CONFIG_JSON` support converts JSON to TOML at startup for compatibility, but only a subset of fields (`url`, `command`, `args`) are converted. For full MCP server configuration (e.g., `bearer_token_env_var`, `env` blocks), use native TOML.

---

## OpenShell Sandbox

[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) is an open-source sandbox runtime for AI agents. The `Containerfile.openshell` builds a Codex sandbox image based on `quay.io/aipcc/agentic-ci/openshell` (RHEL 10). This variant does not include the RHOAI entrypoint or session persistence — it is intended for ephemeral sandbox sessions.

> Tested on: OpenShell gateway v0.0.86, OpenShift 4.21, Codex CLI v0.144.0, Qwen3.6-27B.

### Prerequisites

- [Helm](https://helm.sh/) 3+ installed locally
- [OpenShell CLI](https://docs.nvidia.com/openshell/about/installation) installed locally (`openshell --version` should print `0.0.58` or later)
- The Kubernetes Agent Sandbox CRD must be installed: `oc get crd sandboxes.agents.x-k8s.io`
- A vLLM endpoint reachable from within the cluster

### Step 1: Install the OpenShell gateway

```bash
export OPENSHELL_NAME=openshell

# On shared clusters, use a unique name to avoid ClusterRole conflicts:
# export OPENSHELL_NAME=openshell-<your-namespace>

helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
  --version 0.0.86 \
  --namespace <your-namespace> \
  --set podSecurityContext.fsGroup=null \
  --set securityContext.runAsUser=null \
  --set server.auth.allowUnauthenticatedUsers=true \
  --set fullnameOverride=${OPENSHELL_NAME}

oc rollout status statefulset/${OPENSHELL_NAME} --timeout=120s
```

Grant the privileged SCC to the sandbox service account:

```bash
oc adm policy add-scc-to-user privileged -z ${OPENSHELL_NAME}-sandbox -n <your-namespace>
```

### Step 2: Connect the OpenShell CLI

Extract the mTLS certificates and register the gateway:

```bash
(umask 077 && mkdir -p ~/.config/openshell/gateways/codex-cluster/mtls)

oc get secret openshell-client-tls \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > ~/.config/openshell/gateways/codex-cluster/mtls/ca.crt

oc get secret openshell-client-tls \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ~/.config/openshell/gateways/codex-cluster/mtls/tls.crt

(umask 077 && oc get secret openshell-client-tls \
  -o jsonpath='{.data.tls\.key}' | base64 -d > ~/.config/openshell/gateways/codex-cluster/mtls/tls.key)

oc port-forward svc/${OPENSHELL_NAME} 18080:8080 &
openshell gateway add https://127.0.0.1:18080 --local --name codex-cluster
openshell status
```

### Step 3: Build the sandbox image

Build inside the cluster so the internal registry can serve it to sandbox pods:

```bash
cd agents/codex/deployment

oc create imagestream codex-sandbox

cat <<'EOF' | oc apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: codex-sandbox
spec:
  output:
    to:
      kind: ImageStreamTag
      name: codex-sandbox:latest
  source:
    type: Binary
  strategy:
    dockerStrategy:
      dockerfilePath: Containerfile.openshell
    type: Docker
EOF

oc start-build codex-sandbox --from-dir=. --follow
```

### Step 4: Create a sandbox and test

```bash
openshell sandbox create \
  --name codex \
  --from image-registry.openshift-image-registry.svc:5000/<your-namespace>/codex-sandbox:latest \
  -- sleep infinity

openshell sandbox list
```

Test Codex inside the sandbox:

```bash
oc exec codex -c agent -- bash -c '
  export OPENAI_BASE_URL="http://<vllm-service>.<namespace>.svc.cluster.local/v1"
  export OPENAI_API_KEY="dummy"
  export CODEX_API_KEY="dummy"
  codex exec \
    -c model_provider=vllm \
    -c model="<model-name>" \
    -c model_providers.vllm.name="vLLM" \
    -c model_providers.vllm.base_url="${OPENAI_BASE_URL}" \
    -c model_providers.vllm.supports_websockets=false \
    -c model_supports_reasoning_summaries=false \
    --sandbox danger-full-access \
    --skip-git-repo-check \
    "What is 2+2? Reply with just the number."
'
```

### Cleanup

```bash
openshell sandbox delete codex
helm uninstall openshell -n <your-namespace>
oc delete imagestream codex-sandbox
oc delete buildconfig codex-sandbox
```
