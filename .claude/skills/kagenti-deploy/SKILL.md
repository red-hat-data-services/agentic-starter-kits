---
name: kagenti-deploy
description: >
  Deploy A2A-compliant agents to OpenShift/Kubernetes with kagenti integration. 
  Use this skill when the user wants to deploy an agent with kagenti, mentions 
  "kagenti deployment", "A2A agent deployment", "Agent Runtime", "Agent Card", 
  or asks to deploy an agent that should be visible in kagenti UI. Also use 
  when they mention the /.well-known/agent-card.json or /.well-known/agents.json 
  endpoints, or ask about agent discovery and cataloging in OpenShift.
---

# Kagenti Agent Deployment

Deploy A2A-protocol agents to OpenShift/Kubernetes with full kagenti integration, making them discoverable in the kagenti UI for agent management and orchestration.

## What this skill does

This skill orchestrates the complete deployment of A2A-compliant agents with kagenti:

1. **Prepares the agent** - Initializes environment and dependencies
2. **Builds and pushes container images** - Creates container images with proper A2A endpoints
3. **Ensures kagenti labels** - Adds required labels to deployment manifests
4. **Deploys to cluster** - Uses Helm to deploy the agent
5. **Applies Agent Runtime CR** - Creates kagenti custom resource for agent discovery
6. **Verifies integration** - Confirms Agent Card creation and kagenti synchronization

## When to use this skill

Use this skill when:
- User wants to deploy an agent with kagenti integration
- User mentions "kagenti", "A2A deployment", "Agent Runtime", or "Agent Card"
- User asks to make an agent visible in kagenti UI
- User wants to deploy an agent that implements the A2A protocol
- User asks about agent discovery, cataloging, or orchestration on OpenShift

## Prerequisites

Before starting, verify these are available:
- `oc` CLI configured and authenticated to the target cluster
- `helm` (version 3.x)
- `podman` or `docker` for building container images
- `make` and `bash` available
- Access to a container registry (e.g., quay.io)
- Kagenti installed on the cluster (check: `oc get pods -n kagenti-system`)

## A2A Protocol Requirements

For an agent to work with kagenti, it must:
- Expose `/.well-known/agent-card.json` endpoint
- Return valid A2A agent card JSON with agent metadata
- Implement A2A JSON-RPC protocol for agent-to-agent communication
- Have health check endpoint at `/health`

## Deployment Workflow

### Step 1: Navigate to agent directory

```bash
cd agents/<framework>/<agent_name>/
```

The agent must have:
- `Makefile` with standard targets
- `agent.yaml` with agent metadata
- `.env.example` or `template.env` for configuration template

### Step 2: Initialize and configure

```bash
make init  # Creates .env from .env.example (or template.env for a2a-langgraph-crewai)
```

Edit `.env` to set required variables:
- `API_KEY` - API key for LLM provider
- `BASE_URL` - LLM provider endpoint (must end with `/v1`)
- `MODEL_ID` - Model identifier
- `CONTAINER_IMAGE` - Registry path where images will be pushed

Verify required env vars are set:
```bash
# Check agent.yaml for required variables
grep -A 10 "required:" agent.yaml
```

### Step 3: Set up Python environment

```bash
make env  # Creates venv and installs dependencies with uv
```

This runs `uv sync --python 3.12`.

### Step 4: Build container image

```bash
make build
```

This:
- Validates required env vars
- Builds container image with proper tags
- For A2A agents, may create multiple tags (e.g., `:crew` and `:langgraph`)

Verify build succeeded:
```bash
podman images | grep <agent-name>
# or
docker images | grep <agent-name>
```

### Step 5: Push to registry

```bash
make push
```

Ensure you're authenticated to the registry first:
```bash
podman login quay.io
# or
docker login quay.io
```

### Step 6: Verify and enforce kagenti labels in deployment charts

**CRITICAL**: The deployment charts must include protocol labels for discovery. This skill assumes agents use specialized charts (like `charts/a2a-langgraph-crewai/`) that include these labels.

**Required labels in the chart templates**:
```yaml
metadata:
  labels:
    protocol.kagenti.io/a2a: "true"
```

**Optional protocol labels** (if agent supports multiple protocols):
```yaml
    protocol.kagenti.io/openai: "true"  # If OpenAI-compatible
    protocol.kagenti.io/mcp: "true"     # If MCP-compatible
```

**Important**: The `kagenti.io/type: agent` label is **automatically added by the kagenti controller** when you create the AgentRuntime CR in Step 9. You do NOT need to add this label to the chart templates. Only the protocol labels are required in the chart.

**Verify the chart has protocol labels**:

First, identify which chart the agent uses by checking its Makefile:
```bash
grep "CHART_DIR" Makefile
```

Then verify the chart templates include protocol labels:
```bash
grep -r "protocol.kagenti.io" <chart-directory>/templates/
```

**Expected output** should show protocol labels in deployment files like:
```yaml
    protocol.kagenti.io/a2a: "true"
```

**If protocol labels are missing**:
- Check if this is truly an A2A agent that needs kagenti integration
- The agent may need a specialized chart - consult with the user
- Standard `charts/agent/` template does not include kagenti labels by design

**ENFORCEMENT**: If the grep returns no results for `protocol.kagenti.io`, STOP and inform the user that the chart templates do not include protocol labels. Ask if they want to:
1. Create a specialized chart for this agent with protocol labels
2. Add protocol labels to the existing chart
3. Continue without kagenti integration

### Step 7: Deploy with Helm

**Detect and use the active namespace**: The deployment will use the current `oc` context namespace. Capture it for use in subsequent steps.

```bash
# Get the current active namespace
NAMESPACE=$(oc project -q)
echo "Deploying to namespace: $NAMESPACE"
```

If you need to switch to a different namespace first:
```bash
oc project <target-namespace>
NAMESPACE=$(oc project -q)
```

Deploy the agent:
```bash
make deploy
```

**Note**: The Makefile deploy target uses the current `oc` context namespace. The same namespace will be used throughout all subsequent steps (labeling, CR creation, verification).

This typically:
- Deploys Helm chart with agent resources to the current namespace
- For A2A agents, may do two-phase deploy (services/routes first, then deployments with public URLs)
- Waits for pods to be ready

**Verify deployment** in the target namespace:
```bash
oc get pods -n $NAMESPACE
oc get routes -n $NAMESPACE
```

**Check health endpoint**:
```bash
ROUTE=$(oc get route <agent-name> -n $NAMESPACE -o jsonpath='{.spec.host}')
curl https://$ROUTE/health
# Expected: {"status":"healthy"}
```

**Verify A2A endpoint**:
```bash
curl -sS https://$ROUTE/.well-known/agent-card.json
# Should return valid JSON with agent metadata
```

### Step 8: Label namespace for kagenti discovery

Label the target namespace to enable kagenti discovery:
```bash
oc label namespace $NAMESPACE kagenti-enabled=true --overwrite
```

This tells kagenti to watch this namespace for agents.

**Note**: The deployment labels should already be in the chart templates (verified in Step 6). If they're missing, the chart templates need to be updated before proceeding.

### Step 9: Apply Agent Runtime CR

Create and apply the AgentRuntime custom resource. This tells kagenti about the agent and **automatically creates the corresponding AgentCard CR**.

**AgentRuntime structure**:
```yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: <agent-name>-runtime
  # namespace omitted - uses current oc context
  labels:
    app.kubernetes.io/name: <agent-name>
spec:
  type: agent
  protocol: a2a
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <deployment-name>
```

**Check if AgentRuntime.yaml exists in the agent directory** as a reference:
```bash
ls -la AgentRuntime.yaml
```

**Recommended approach**: Always create AgentRuntime inline to avoid mutating tracked files and ensure correct namespace:
```bash
# Read the existing file for deployment names if it exists, then create inline
cat <<EOF | oc apply -f -
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: <agent-name>-runtime
  # namespace omitted - uses current oc context
  labels:
    app.kubernetes.io/name: <agent-name>
spec:
  type: agent
  protocol: a2a
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <deployment-name>
EOF
```

**For multi-deployment agents** (like a2a-langgraph-crewai with separate langgraph and crew pods), create one AgentRuntime for each deployment:
```bash
cat <<EOF | oc apply -f -
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: <langgraph-agent>-runtime
  # namespace omitted - uses current oc context
  labels:
    app.kubernetes.io/name: <langgraph-agent>
spec:
  type: agent
  protocol: a2a
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <langgraph-deployment-name>
---
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: <crew-agent>-runtime
  # namespace omitted - uses current oc context
  labels:
    app.kubernetes.io/name: <crew-agent>
spec:
  type: agent
  protocol: a2a
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <crew-deployment-name>
EOF
```

**What happens next**: The kagenti controller will:
1. Detect the AgentRuntime CR
2. Fetch the agent card from the `/.well-known/agent-card.json` endpoint
3. Automatically create a corresponding AgentCard CR with the agent's metadata
4. Update the AgentCard status with sync information

### Step 10: Verify kagenti integration

**Check that AgentRuntime was created**:
```bash
oc get agentruntime -n $NAMESPACE
```

**Check for AgentCards** (created automatically by AgentRuntime):
```bash
oc get agentcard -n $NAMESPACE
```

Expected output shows SYNCED status as `True`:
```
NAME                      PROTOCOL   KIND         TARGET                  AGENT                        SYNCED
<agent-name>-runtime      a2a        Deployment   <deployment-name>       <Agent Display Name>         True
```

**Check AgentCard sync status**:
```bash
oc get agentcard -n $NAMESPACE -o yaml | grep -A 15 "status:"
```

Look for:
```yaml
status:
  conditions:
  - type: Synced
    status: "True"
    reason: SyncSuccessful
  card:
    name: <Agent Display Name>
    protocol: a2a
```

**Verify deployment labels** are present:
```bash
oc get deployment <deployment-name> -n $NAMESPACE -o jsonpath='{.metadata.labels}' | python3 -m json.tool
```

Should include:
```json
{
  "kagenti.io/type": "agent",
  "protocol.kagenti.io/a2a": "true"
}
```

Note: The `kagenti.io/type: agent` label was automatically added by the kagenti controller when you created the AgentRuntime. The `protocol.kagenti.io/a2a` label comes from the chart templates.

**Verify namespace label**:
```bash
oc get namespace $NAMESPACE -o jsonpath='{.metadata.labels.kagenti-enabled}'
```

Should return: `true`

**Check kagenti controller logs**:
```bash
oc logs -n kagenti-system deployment/kagenti-controller-manager --tail=50 | grep $NAMESPACE
```

Look for:
- `Fetching A2A agent card` messages for your agent
- `Successfully fetched agent card` messages
- No error messages about the agent

**Common success indicators**:
- AgentRuntime exists in the namespace
- AgentCard exists with same name as AgentRuntime
- AgentCard status shows `Synced: True`
- Deployment has `kagenti.io/type: agent` (controller-added) and protocol labels (chart-defined)
- Namespace has `kagenti-enabled: true` label
- Controller logs show successful card fetch

### Step 11: Verify in kagenti UI

Access the kagenti UI (URL depends on cluster):
```bash
# Get the route
oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}'
```

Open in browser: `https://<kagenti-ui-host>`

Verify:
- Agent appears in the agent list
- Protocol badges show correctly (A2A, OpenAI, etc.)
- Sync status shows as "Synced"
- Agent metadata is displayed correctly

## Verification Script

A comprehensive verification script is available at [`scripts/verify-kagenti.sh`](scripts/verify-kagenti.sh).

Usage:
```bash
# From the skill directory
chmod +x scripts/verify-kagenti.sh
./scripts/verify-kagenti.sh <namespace>

# Example
./scripts/verify-kagenti.sh agents
```

The script checks:
1. Namespace has `kagenti-enabled: true` label
2. Deployments have required kagenti labels
3. AgentRuntime CRs exist
4. AgentCard CRs are created and synced
5. Overall deployment status

Returns `[PASS]`, `[FAIL]`, or `[WARN]` for each check.

## Troubleshooting

### Agents not appearing in kagenti UI

1. **Check AgentCard/AgentRuntime status**:
   ```bash
   oc get agentcard <agent-name> -n <namespace> -o yaml
   ```
   Look for error conditions in status.

2. **Verify deployment labels**:
   ```bash
   oc get deployment <agent-name> -n <namespace> -o jsonpath='{.metadata.labels}' | python3 -m json.tool
   ```

3. **Check namespace label**:
   ```bash
   oc get namespace <namespace> -o jsonpath='{.metadata.labels}'
   ```

4. **Verify A2A endpoint is responding**:
   ```bash
   ROUTE=$(oc get route <agent-name> -n <namespace> -o jsonpath='{.spec.host}')
   curl -sS "https://$ROUTE/.well-known/agent-card.json"
   ```
   Should return valid JSON with agent metadata.

5. **Check kagenti controller logs**:
   ```bash
   oc logs -n kagenti-system deployment/kagenti-controller-manager --tail=100
   ```
   Look for errors related to your agent.

6. **Verify pods are running**:
   ```bash
   oc get pods -n <namespace>
   ```
   All pods should be in `Running` state (1/1).

### Pods in CrashLoopBackOff

1. Check pod logs:
   ```bash
   oc logs <pod-name> -n <namespace>
   ```

2. Common issues:
   - Missing or incorrect environment variables
   - Dependency version conflicts (e.g., a2a-sdk version)
   - Port conflicts or binding issues

### AgentCard not syncing

1. First check the AgentRuntime (not AgentCard directly):
   ```bash
   oc get agentruntime -n $NAMESPACE -o yaml
   ```
   
   Verify the targetRef points to the correct deployment.

2. Check if the deployment exists and has the right labels:
   ```bash
   oc get deployment <deployment-name> -n $NAMESPACE -o yaml | grep -A 5 "labels:"
   ```

3. Verify the A2A endpoint is responding:
   ```bash
   ROUTE=$(oc get route <agent-name> -n $NAMESPACE -o jsonpath='{.spec.host}')
   curl -sS "https://$ROUTE/.well-known/agent-card.json"
   ```
   
   Should return valid JSON. If it errors, the kagenti controller can't fetch the card.

4. Check AgentCard status for error messages:
   ```bash
   oc get agentcard -n $NAMESPACE -o yaml | grep -A 20 "status:"
   ```
   
   Look for error conditions or reasons for sync failure.

5. Delete and recreate the AgentRuntime (this will recreate the AgentCard):
   ```bash
   oc delete agentruntime <agent-name>-runtime -n $NAMESPACE
   oc apply -f AgentRuntime.yaml
   ```
   
   Wait 10-20 seconds and check again:
   ```bash
   oc get agentcard -n $NAMESPACE
   ```

## Important Notes

- **A2A Endpoint**: The standard A2A endpoint is `/.well-known/agent-card.json`. All A2A agents must expose this endpoint.
  
- **AgentRuntime creates AgentCard**: When you create an AgentRuntime CR, the kagenti controller automatically creates a corresponding AgentCard CR by fetching metadata from the agent's endpoint. You only need to create AgentRuntime.

- **Chart requirements**: This skill assumes agents use specialized charts (like `charts/a2a-langgraph-crewai/`) that include the A2A protocol label. The standard `charts/agent/` template does not include these labels by design.

- **Controller-managed vs chart-managed labels**:
  - `kagenti.io/type: agent` - Automatically added by kagenti controller when AgentRuntime CR is created (NOT in chart)
  - `protocol.kagenti.io/a2a: "true"` - Must be defined in chart templates

- **Multi-agent deployments**: Some agents (like a2a-langgraph-crewai) deploy multiple services. Each deployment needs its own AgentRuntime CR.

- **Namespace consistency**: Use the same namespace throughout the entire deployment process - from Helm deploy to AgentRuntime creation to verification.

## Success Criteria

Deployment is successful when:
- Agent pods are running (1/1 Ready)
- Routes are accessible and health checks pass
- Namespace has `kagenti-enabled: true` label
- Deployment has `kagenti.io/type: agent` (added by controller) and protocol labels (from chart)
- AgentRuntime CR is created and references correct deployment
- AgentCard CR exists and shows `SYNCED: True` status
- Agent appears in kagenti UI with correct metadata
- A2A endpoint returns valid agent card JSON

## Example: Complete Deployment Workflow

Here's the complete workflow for deploying the a2a-langgraph-crewai agent with kagenti integration:

```bash
# 1. Navigate to agent directory
cd agents/a2a/langgraph_crewai_agent/

# 2. Initialize configuration
make init  # Creates .env from template.env

# 3. Edit .env with your credentials (required manual step)
# Set: API_KEY, BASE_URL, MODEL_ID, CONTAINER_IMAGE
vim .env  # or nano, code, etc.

# 4. Set up Python environment
make env

# 5. Verify chart has protocol labels
grep -r "protocol.kagenti.io" ../../../charts/a2a-langgraph-crewai/templates/
# Should show: protocol.kagenti.io/a2a: "true"

# 6. Build container image
make build

# 7. Authenticate to container registry (required manual step)
podman login quay.io  # Enter your credentials when prompted

# 8. Push to registry
make push

# 9. Deploy to cluster (uses current oc context namespace)
make deploy

# 10. Get active namespace and label it
NAMESPACE=$(oc project -q)
echo "Deploying to namespace: $NAMESPACE"
oc label namespace $NAMESPACE kagenti-enabled=true --overwrite

# 11. Verify A2A endpoints are responding
LANGGRAPH_ROUTE=$(oc get route a2a-langgraph-agent -n $NAMESPACE -o jsonpath='{.spec.host}')
CREW_ROUTE=$(oc get route a2a-crew-agent -n $NAMESPACE -o jsonpath='{.spec.host}')
curl -sS https://$LANGGRAPH_ROUTE/.well-known/agent-card.json | jq
curl -sS https://$CREW_ROUTE/.well-known/agent-card.json | jq

# 12. Create AgentRuntime CRs (namespace omitted - uses oc context)
cat <<EOF | oc apply -f -
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: a2a-langgraph-agent-runtime
  labels:
    app.kubernetes.io/name: a2a-langgraph-agent
spec:
  type: agent
  protocol: a2a
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: a2a-langgraph-agent
---
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: a2a-crew-agent-runtime
  labels:
    app.kubernetes.io/name: a2a-crew-agent
spec:
  type: agent
  protocol: a2a
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: a2a-crew-agent
EOF

# 13. Run verification script
# This checks all components and reports status
../../../.claude/skills/kagenti-deploy/scripts/verify-kagenti.sh $NAMESPACE

# 14. Access kagenti UI
KAGENTI_UI=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')
echo "Kagenti UI: https://$KAGENTI_UI"
```

**Manual steps required:**
- Step 3: Edit `.env` with your API key, base URL, model ID, and container image path
- Step 7: Authenticate to your container registry with credentials
- Ensure you're in the correct `oc` context/namespace before deploying
