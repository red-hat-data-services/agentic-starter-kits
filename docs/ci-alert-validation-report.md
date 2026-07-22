# CI Alert Validation Report

## Evidence Summary

Timestamps below come from the GitHub Actions Jobs API (`gh run view <run-id> --json jobs`) unless noted as a notify-step or log observation.

| Workflow | Run ID | Event | Failure signal | Notify evidence | Observation |
| --- | --- | --- | --- | --- | --- |
| `Inner Loop Gating` | `29016905658` | `workflow_dispatch` on `main` | `Cluster Behavioral Tests`: failing step `Run shared btest runner` at `2026-07-09T12:07:04Z`; job `completedAt` `2026-07-09T12:07:08Z` | `Notify Slack` completed successfully; `Send Slack notification` step at `2026-07-09T12:07:38Z`; job `completedAt` `2026-07-09T12:07:41Z` | One workflow-level alert was sent 34 seconds after the failing step completed |
| `QG4: Agent Deployment Integration Tests` | `29890165253` | `schedule` on `main` | `langflow-simple-tool-calling-agent`: failing step `Run integration test` at `2026-07-22T04:06:44Z`; job `completedAt` `2026-07-22T04:06:46Z` | `Notify Slack` completed successfully; `Send Slack notification` step at `2026-07-22T04:13:21Z`; log contains `Slack notification sent` | Matrix failures are deduped into one alert after the workflow conclusion is known |

## SLA Measurement Note

- The current notify path emits one alert after the workflow conclusion is known,
  not when the first matrix leg fails.
- For `QG4: Agent Deployment Integration Tests` run `29890165253`, the first
  failing matrix step completed at `2026-07-22T04:06:44Z`, that job's Jobs API
  `completedAt` was `2026-07-22T04:06:46Z`, the final non-notify job
  `completedAt` was `2026-07-22T04:13:15Z`, and `Slack notification sent` was
  logged at `2026-07-22T04:13:21Z`.
- Measured from workflow-level failure/conclusion readiness, the sample meets
  the current expectation because the alert followed the matrix conclusion by
  6 seconds.
- Measured from the first failing matrix job, the same sample exceeds 5 minutes.
  That measurement-basis ambiguity should be reviewed by the team as a follow-up
  runbook/policy clarification.

## Payload Quality Verification

These observations come from the local `render_payload.sh` preview command in
`docs/ci-health-dashboard.md`, using representative `Code Quality` inputs. They
are not from a captured live `Code Quality` failure on `main`.

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
