# One-time ci-testing build artifact cleanup (RHAIENG-6183)

Use this runbook to reduce accumulated OpenShift build artifacts in the shared
`ci-testing` namespace after RHAIENG-6183 lands. Ongoing cleanup is handled by
agent `make undeploy` (Helm release + BC/IS deletion) and `make build-openshift`
(2/1 history limits via `scripts/openshift-build-config.sh`).

## Patch existing BuildConfigs to 2/1 (triggers controller prune)

```bash
oc project ci-testing
for bc in $(oc get bc -o name); do
  oc patch "$bc" --type=merge \
    -p '{"spec":{"successfulBuildsHistoryLimit":2,"failedBuildsHistoryLimit":1}}'
done
```

Alternatively, patch a single agent BC the same way `make build-openshift` does:

```bash
scripts/openshift-build-config.sh patch-history <agent-name> -n ci-testing
```

## Verify counts drop (wait ~5–15 min)

After patching, the build controller prunes excess Build and ConfigMap objects
over several minutes. Re-check until counts stabilize:

```bash
oc get builds --no-headers | wc -l
oc get cm --no-headers | wc -l
```

Optional spot-check that limits applied:

```bash
oc get bc -o custom-columns=NAME:.metadata.name,SUCCESS:.spec.successfulBuildsHistoryLimit,FAILED:.spec.failedBuildsHistoryLimit
```

## Remove stale Helm releases (example)

Orphaned Helm releases may remain after failed integration tests. List and
remove only releases you recognize as stale test agents:

```bash
helm list -n ci-testing
helm uninstall langgraph-ci-failure-summarizer-agent -n ci-testing  # if orphaned
```

Then remove matching BC/IS if still present (agent name must **not** be on the
denylist — see below):

```bash
scripts/openshift-build-config.sh cleanup langgraph-ci-failure-summarizer-agent -n ci-testing
```

## Do not delete

Never run `oc delete all` or blanket ConfigMap delete in `ci-testing`. The
following shared resources must be preserved.

### BuildConfig / ImageStream denylist

`scripts/openshift-build-config.sh` refuses `cleanup` for names in
`CLEANUP_DENYLIST` (see `scripts/openshift-build-config.sh`):

| Resource | Reason |
|----------|--------|
| `postgres` | Shared database for integration tests |
| `minio` | Shared object storage |
| `mcp-automl` | Shared MCP server (autogen agent); use `undeploy-mcp`, not agent `undeploy` |
| `langflow-simple-tool-calling-agent` | Langflow pre-deploy / shared infra |

### Platform and CA bundle ConfigMaps

Do **not** delete namespace service accounts, pull secrets, or platform CA
bundle ConfigMaps, including:

- `config-*-cabundle` (OpenShift injected CA bundles)
- `kube-root-ca.crt`
- `odh-*` (Open Data Hub operator bundles)
- `openshift-service-ca.crt`
- `tempo-sample-*` (observability sample resources)

### Other shared infra

- Langflow routes and deployments tied to `langflow-simple-tool-calling-agent`
- Namespace service accounts and image pull secrets
