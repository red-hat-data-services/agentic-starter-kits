# De-brief: Agentic Workflow Quality Gates

## Snapshot
- Primary target repo: `agentic-starter-kits`
- Source automation repo: `/home/kakella/code/devtools/Summit-on-ROSA/smoke-tests`
- Broader implementation initiative: [RHAIENG-5827](https://redhat.atlassian.net/browse/RHAIENG-5827)
- Porting story: [RHAIENG-5866](https://redhat.atlassian.net/browse/RHAIENG-5866)
- Current phase: `QG2`
- Current execution branch/worktree: `qg2-platform-readiness` at `/home/kakella/code/agentic-starter-kits-worktrees/qg2-platform-readiness`

## Why
- The org wants a layered quality-gates model so cluster/platform/stack issues are caught before they burn time in later agent-level and workflow-level validation.
- The GitLab smoke tests were useful as a starting point, but they mixed multiple gate levels together and were softer than the desired GitHub-native quality-gate model.
- The goal is to make platform failures visible, actionable, and reusable inside a future orchestrated pipeline.

## Phase Split

### Phase 1: QG1
- Cluster readiness
- Implemented as a reusable composite action plus standalone workflow
- Merged via [PR #314](https://github.com/red-hat-data-services/agentic-starter-kits/pull/314)

### Phase 2: QG2
- Platform readiness
- Current branch implements:
  - `.github/scripts/qg2_platform_readiness.py`
  - `.github/actions/run-qg2/action.yml`
  - `.github/workflows/qg2-platform-readiness.yml`
  - dashboard/doc registration updates

### Phase 3: QG3
- Stack readiness
- Deferred until QG2 is committed

## Current QG2 Scope
- operator health
- `DataScienceCluster` existence and `Ready`
- KServe controller/platform readiness

Explicitly out of scope for QG2:
- vLLM endpoint checks
- Langflow/Langfuse/MLflow/MCP Gateway/Keycloak/Postgres component health
- agent deployment or workflow validation

## Current Architectural Assumptions
- Each gate should live in its own composite action under `.github/actions/`
- Each gate should also have a standalone workflow for manual and scheduled runs
- `setup-cluster` remains the shared login/bootstrap layer
- QG2 is a singleton pre-matrix gate, not a per-agent matrix job
- Orchestration-level blocking across QG1 -> QG2 -> QG3 -> QG4 is still future work; today QG2 is a standalone gate unit

## Latest Reality Check

### Key direction change
- For the current work, the target is **RHOAI2**, not a generic `ODH/RHOAI` abstraction
- The implementation should therefore align first to the actual `rhoai2` cluster shape we have access to
- `odh` remains unvalidated and is not the current target assumption

### Live cluster observations
- Cluster: `https://api.agen-e2e-rhoai2.p5ui.p3.openshiftapps.com:443`
- User: `cluster-admin`
- Project: `ci-testing`
- Operator namespace present: `redhat-ods-operator`
- Operator deployment observed: `rhods-operator` with `ready=3 desired=3`
- Operator CSV observed: `rhods-operator.3.5.0-ea.2 phase=Succeeded`
- `DataScienceCluster` observed: `default-dsc phase=Ready`
- KServe deployment observed: `redhat-ods-applications/kserve-controller-manager ready=1 desired=1`

### Consequences for QG2
- The original `rhods-operator-controller-manager` assumption was wrong for the live `rhoai2` cluster and had to be corrected
- KServe pod-phase checks were not strong enough; deployment `readyReplicas` vs `spec.replicas` is a better signal here
- A genuinely absent `DataScienceCluster` should produce a named `datasciencecluster_ready` failure, not a generic `oc_command` error
- The current QG2 implementation is now intentionally hardened to match those specific `rhoai2` realities

## Current Assessment
- QG2 now matches the current `rhoai2` cluster much better than the initial generic draft did
- For `rhoai2`, it is close to a reliable platform-readiness gate
- It is **not** yet claimed as universally correct for both `rhoai` and `odh`
- The remaining larger gap is orchestration wiring: QG2 exists as a validated standalone gate, but it does not yet block downstream gates in the actual CI pipeline

## Sources
- Local strategy note: `/home/kakella/Downloads/agentic-workflow-strat.md`
- GitLab source: `/home/kakella/code/devtools/Summit-on-ROSA/smoke-tests/.gitlab-ci.yml`
- Jira: [RHAIENG-5827](https://redhat.atlassian.net/browse/RHAIENG-5827)
- Jira: [RHAIENG-5866](https://redhat.atlassian.net/browse/RHAIENG-5866)
- GitHub discussion: [#285](https://github.com/red-hat-data-services/agentic-starter-kits/discussions/285)
