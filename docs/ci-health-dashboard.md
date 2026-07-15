# CI Health Dashboard

Static HTML summary of QG8 in-scope GitHub Actions workflows for `agentic-starter-kits`.

## Scope

The dashboard covers these workflows on `main` and scheduled or manual shared-branch runs:

| Workflow file | Display name |
|---------------|--------------|
| `code-quality.yml` | Code Quality |
| `agent-tests.yml` | Agent Tests |
| `eval-gating.yml` | Inner Loop Gating |
| `agent-deployment-test.yaml` | QG4: Agent Deployment Integration Tests |

Pull request runs are excluded from the summary to keep the page focused on shared-branch health.

## Data source

- **Live mode:** GitHub Actions REST API via `GITHUB_TOKEN` with `actions: read`
- **Fixture mode:** `.github/scripts/fixtures/ci-runs-sample.json` for offline generation and demos (timestamps must be within the last 7 days for pass-rate display)

## Update cadence

- **Push model:** rebuilds when any in-scope CI workflow completes on `main` or via `schedule` (`workflow_run` trigger in `.github/workflows/ci-health-pages.yml`)
- Manual refresh via **Actions → CI Health Pages → Run workflow**
- Also rebuilds when dashboard generator or workflow files change on `main`

## Policy reference

Routing, ownership, severity, and MVP handling expectations for these alerts are
defined in [CI Alert Policy](./ci-alert-policy.md).

## Slack alerts

The same four workflows also send immediate Slack alerts when a shared-branch run fails:

- `Code Quality`
- `Agent Tests`
- `Inner Loop Gating`
- `QG4: Agent Deployment Integration Tests`

The event list below is the union of the supported notification triggers across those workflows. Individual workflows do not all define the same trigger set.

Included events:

- `push` on `main`
- `schedule`
- `workflow_dispatch` when the selected ref is `main`

Excluded events:

- `pull_request`
- `workflow_dispatch` on non-`main` branches
- successful runs

The Slack message complements this dashboard:

- Slack is the fast failure signal
- GitHub Actions is the source of full logs
- the CI dashboard is the shared health summary and historical view

### Secret setup

Add this repository secret under **Settings → Secrets and variables → Actions**:

- `SLACK_WEBHOOK_URL`

This repo only supports `SLACK_WEBHOOK_URL` for Slack notifications. Do not store webhook URLs in workflow files, docs examples, or repository variables.

### Local payload preview

Render and preview the Slack payload without sending a message:

```bash
WORKFLOW_NAME="Code Quality" \
EVENT_NAME="workflow_dispatch" \
REF_NAME="main" \
STATUS="failure" \
RUN_URL="https://github.com/red-hat-data-services/agentic-starter-kits/actions/runs/123456789" \
DASHBOARD_URL="https://red-hat-data-services.github.io/agentic-starter-kits/" \
REPOSITORY="red-hat-data-services/agentic-starter-kits" \
FAILED_JOBS_JSON='["lint", "type-check"]' \
TIMESTAMP="2026-07-09T07:30:00Z" \
bash .github/actions/notify-slack/render_payload.sh > /tmp/slack-payload.json

bash .github/actions/notify-slack/notify.sh --preview /tmp/slack-payload.json
```

### Controlled validation

To validate end-to-end delivery after the secret is present:

1. Open one in-scope workflow from the **Actions** tab.
2. Select the `main` branch in **Run workflow**.
3. Trigger a controlled failure.
4. Confirm exactly one Slack message arrives for the failed run.
5. Confirm the message includes the failed job names, workflow run link, and dashboard link.
6. Confirm a PR failure or a manual dispatch from a non-`main` branch does not post to Slack.

## Enable GitHub Pages before merge

You can enable Pages while the PR is still in review:

1. Repo admin opens **Settings → Pages**
2. Set **Build and deployment → Source** to **GitHub Actions**
3. Merge is not required for this setting

After the workflow file exists on your PR branch:

1. Open **Actions → CI Health Pages**
2. Click **Run workflow**
3. Optional: enable **use_fixture** for a deterministic demo before merge
4. Open the deployment URL from the workflow summary

Once the PR merges to `main`, each qualifying CI completion keeps the page current.

## Local preview

```bash
python .github/scripts/generate_ci_health_page.py \
  --input .github/scripts/fixtures/ci-runs-sample.json \
  --output site/index.html

python -m http.server 8080 --directory site
```

Live API mode:

```bash
export GITHUB_TOKEN="$(gh auth token)"
python .github/scripts/generate_ci_health_page.py \
  --repository red-hat-data-services/agentic-starter-kits \
  --output site/index.html
```

## Tests

```bash
python -m pytest .github/scripts/tests/test_generate_ci_health_page.py -v
```
