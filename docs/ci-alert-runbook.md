# CI Alert Runbook

## Scope

This runbook covers the shared-branch CI Slack alerts for
`agentic-starter-kits`.

| Workflow | Canonicality | Severity fingerprint | Qualifying events |
| --- | --- | --- | --- |
| `Code Quality` | Non-canonical supporting signal | None yet | `push` on `main`, `workflow_dispatch` on `main` |
| `Agent Tests` | Non-canonical supporting signal | None yet | `push` on `main`, `workflow_dispatch` on `main` |
| `Inner Loop Gating` | Canonical | `QG7` | `push` on `main` when matching eval/behavioral paths change, `workflow_dispatch` on `main` |
| `QG1: Cluster Readiness` | Canonical | `QG1` | `schedule`, `workflow_dispatch` on `main` |
| `QG2: Platform Readiness` | Canonical | `QG2` | `schedule`, `workflow_dispatch` on `main` |
| `QG4: Agent Deployment Integration Tests` | Canonical | `QG4` | `schedule`, `workflow_dispatch` on `main` |

## Routing and Ownership

- **Route:** repository secret `SLACK_WEBHOOK_URL`
- **Accountable owner group:** `@aaet-tooling-experience`
- **Human handling model:** `notify-only`

## QG2 Cluster Access Requirements

`QG2: Platform Readiness` authenticates via the `OC_TOKEN` secret through
`.github/actions/setup-cluster` only as a bootstrap identity, then mints a
short-lived token for the dedicated `qg2-readiness` service account in
`ci-testing` before the checker runs. That dedicated identity needs
cluster-wide (not just namespace-scoped) read access to `deployments`,
`clusterserviceversions` (`csv`), and `datasciencecluster` — QG2 lists
`datasciencecluster` and the KServe-labeled `deployment` cluster-wide
(`-A`) to distinguish a genuinely absent resource from an RBAC error, so a
token scoped to a single namespace will misreport as `oc_command`/`Forbidden`
failures instead of clean
`operator_health`/`kserve_controller`/`datasciencecluster_ready` results.
The bootstrap `github-actions` service account only needs permission to
mint `serviceaccounts/token` in `ci-testing`.

## Dedupe and Timing Semantics

- One Slack alert is emitted per qualifying workflow run.
- The alert is emitted after the workflow conclusion is known.
- Matrix failures are aggregated into one workflow-level alert with a failed-job list.
- If the GitHub jobs API lookup fails, the alert still sends without job detail.

## Severity Interpretation

- `QG1` is the highest current action priority because lower-numbered canonical
  QGs outrank higher-numbered ones.
- `QG2` is the next current canonical priority and should be triaged after
  `QG1` but ahead of `QG4`, `QG7`, and supporting signals.
- `QG4` is the next current canonical priority and should be triaged after
  `QG1` and `QG2` but ahead of `QG7` and supporting signals.
- `QG7` is the next current canonical priority and should be triaged after
  `QG4` but ahead of supporting signals.
- `Code Quality` and `Agent Tests` are supporting signals without canonical
  fingerprints yet; treat them as operationally important but lower urgency
  unless the failure is novel, repeated, or blocks shared-branch progress.

## Non-alert Cases

The current implementation does not send a team Slack alert for:

- `pull_request` runs
- `workflow_dispatch` runs on non-`main` branches
- successful workflow runs

If one of these runs fails, responders should expect no Slack message and
should inspect the GitHub Actions run directly.

## SLA Path

1. A qualifying shared-branch workflow run fails.
2. The repository posts one alert into the shared CI Slack destination.
3. The alert should arrive within 5 minutes of workflow conclusion.
4. The responder opens the workflow run first, then the CI dashboard.
5. The responder follows the validation and triage guidance in this runbook.

## Responder Checklist

1. Open the workflow run link from Slack and confirm the run is a qualifying
   shared-branch failure.
2. Review the failed-job list in Slack; if it is missing, use the workflow run
   page because the alert may have sent without job detail.
3. Use the workflow logs to decide whether the failure is transient, already
   known, or a new defect.
4. Open the CI health dashboard to check whether the same workflow or related
   shared-branch signals are already failing.
5. Prioritize follow-up using the severity interpretation in this runbook and
   the proposed team SLA table below.
6. Route the follow-up through the normal team remediation or backlog path
   because this MVP remains `notify-only`.

## Proposed Team SLA (discussion item)

| Severity bucket | Current signal mapping | Proposed acknowledgement window | Proposed triage target |
| --- | --- | --- | --- |
| Highest current priority | `QG1` | Within 1 business hour | Same business day |
| Next current priority | `QG2` | Within 1 business hour | Same business day |
| Next current priority | `QG4` | Within 1 business hour | Same business day |
| Next current priority | `QG7` | Within 4 business hours | Next business half-day |
| Supporting signals | `Code Quality`, `Agent Tests` | By next business day | Next business day or convert to backlog follow-up if duplicate |

## Validation Evidence

- Current evidence snapshot: [CI Alert Validation Report](./ci-alert-validation-report.md)
- The report records the exact `main` run IDs and observed notify-job timings
  used to validate this runbook.
