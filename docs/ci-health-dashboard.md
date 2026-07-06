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
- **Fixture mode:** `.github/scripts/fixtures/ci-runs-sample.json` for offline generation and demos

## Update cadence

- Daily at `06:00 UTC` via `.github/workflows/ci-health-pages.yml`
- Manual refresh via **Actions → CI Health Pages → Run workflow**

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

Once the PR merges to `main`, scheduled runs keep the page current.

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
