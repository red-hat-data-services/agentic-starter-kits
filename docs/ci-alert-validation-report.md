# CI Alert Validation Report

## Evidence Summary

| Workflow | Run ID | Event | Failure signal | Notify evidence | Observation |
| --- | --- | --- | --- | --- | --- |
| `Inner Loop Gating` | `29016905658` | `workflow_dispatch` on `main` | `Cluster Behavioral Tests` failed at `2026-07-09T12:07:04Z` | `Notify Slack` completed successfully; `Send Slack notification` completed at `2026-07-09T12:07:38Z` | One workflow-level alert was sent 34 seconds after the failing job completed |
| `QG4: Agent Deployment Integration Tests` | `29890165253` | `schedule` on `main` | `langflow-simple-tool-calling-agent` failed at `2026-07-22T04:06:44Z` | `Notify Slack` completed successfully; log contains `Slack notification sent` at `2026-07-22T04:13:21Z` | Matrix failures are deduped into one alert after the workflow conclusion is known |

## Coverage Review

- `Code Quality` and `Agent Tests` both use the same `Notify Slack` job shape,
  the same `should_notify.sh` gate, the same `.github/actions/notify-slack`
  composite action, and the same dashboard URL wiring.
- Recent qualifying `main` failures were not available for `Agent Tests`, and
  recent `Code Quality` failures were limited to PR history, so live evidence
  for those two workflows is configuration-equivalence rather than a fresh
  shared-branch failure sample.
