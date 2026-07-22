# CI Alert Runbook

## Scope

This runbook covers the shared-branch CI Slack alerts for
`agentic-starter-kits`.

| Workflow | Canonicality | Severity fingerprint | Qualifying events |
| --- | --- | --- | --- |
| `Code Quality` | Non-canonical supporting signal | None yet | `push` on `main`, `workflow_dispatch` on `main` |
| `Agent Tests` | Non-canonical supporting signal | None yet | `push` on `main`, `workflow_dispatch` on `main` |
| `Inner Loop Gating` | Canonical | `QG7` | `push` on `main` when matching eval/behavioral paths change, `workflow_dispatch` on `main` |
| `QG4: Agent Deployment Integration Tests` | Canonical | `QG4` | `schedule`, `workflow_dispatch` on `main` |

## Routing and Ownership

- **Route:** repository secret `SLACK_WEBHOOK_URL`
- **Accountable owner group:** `@aaet-tooling-experience`
- **Human handling model:** `notify-only`

## Dedupe and Timing Semantics

- One Slack alert is emitted per qualifying workflow run.
- The alert is emitted after the workflow conclusion is known.
- Matrix failures are aggregated into one workflow-level alert with a failed-job list.
- If the GitHub jobs API lookup fails, the alert still sends without job detail.

## SLA Path

1. A qualifying shared-branch workflow run fails.
2. The repository posts one alert into the shared CI Slack destination.
3. The alert should arrive within 5 minutes of workflow failure.
4. The responder opens the workflow run first, then the CI dashboard.
5. The responder follows the validation and triage guidance in this runbook.

## Proposed Team SLA (discussion item)

| Severity bucket | Current signal mapping | Proposed acknowledgement window | Proposed triage target |
| --- | --- | --- | --- |
| Highest current priority | `QG4` | Within 1 business hour | Same business day |
| Next current priority | `QG7` | Within 4 business hours | Next business half-day |
| Supporting signals | `Code Quality`, `Agent Tests` | By next business day | Next business day or convert to backlog follow-up if duplicate |
