# CI Alert Validation Report

## Evidence Summary

| Workflow | Run ID | Event | Failure signal | Notify evidence | Observation |
| --- | --- | --- | --- | --- | --- |
| `Inner Loop Gating` | `29016905658` | `workflow_dispatch` on `main` | `Cluster Behavioral Tests` failed at `2026-07-09T12:07:04Z` | `Notify Slack` completed successfully; `Send Slack notification` completed at `2026-07-09T12:07:38Z` | One workflow-level alert was sent 34 seconds after the failing job completed |
| `QG4: Agent Deployment Integration Tests` | `29890165253` | `schedule` on `main` | `langflow-simple-tool-calling-agent` failed at `2026-07-22T04:06:44Z` | `Notify Slack` completed successfully; log contains `Slack notification sent` at `2026-07-22T04:13:21Z` | Matrix failures are deduped into one alert after the workflow conclusion is known |

## SLA Measurement Note

- The current notify path emits one alert after the workflow conclusion is known,
  not when the first matrix leg fails.
- For `QG4: Agent Deployment Integration Tests` run `29890165253`, the first
  failing matrix job completed at `2026-07-22T04:06:44Z`, the final non-notify
  job completed at `2026-07-22T04:13:15Z`, and `Slack notification sent` was
  logged at `2026-07-22T04:13:21Z`.
- Measured from workflow-level failure/conclusion readiness, the sample meets
  the current expectation because the alert followed the matrix conclusion by
  6 seconds.
- Measured from the first failing matrix job, the same sample exceeds 5 minutes.
  That measurement-basis ambiguity should be reviewed by the team as a follow-up
  runbook/policy clarification.

## Payload Quality Verification

- The rendered header preserves the workflow name: `CI Failure: Code Quality`.
- The payload fields preserve the expected event/ref context:
  `workflow_dispatch` on `main`.
- The failed-job section lists the expected workflow-level job names:
  `lint` and `type-check`.
- The payload includes direct links to both the workflow run and the CI
  dashboard for responder navigation.

## Coverage Review

- `Code Quality` and `Agent Tests` both use the same `Notify Slack` job shape,
  the same `should_notify.sh` gate, the same `.github/actions/notify-slack`
  composite action, and the same dashboard URL wiring.
- Recent qualifying `main` failures were not available for `Agent Tests`, and
  recent `Code Quality` failures were limited to PR history, so live evidence
  for those two workflows is configuration-equivalence rather than a fresh
  shared-branch failure sample.
