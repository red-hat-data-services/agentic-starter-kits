#!/usr/bin/env python3
"""
Generate a static CI health dashboard from GitHub Actions workflow runs.

Used by the ci-health-pages workflow to publish a read-only summary for the
QG8 in-scope workflows on main and scheduled/nightly executions.

Environment variables (optional):
    GITHUB_TOKEN      Token with actions:read (defaults to GITHUB_TOKEN in CI)
    GITHUB_REPOSITORY owner/repo (required for live API mode)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

API_ROOT = "https://api.github.com"
WORKFLOWS = (
    {
        "file": "code-quality.yml",
        "name": "Code Quality",
        "description": "Lint, format, and markdown checks on main and PRs.",
    },
    {
        "file": "agent-tests.yml",
        "name": "Agent Tests",
        "description": "Unit tests for agent templates.",
    },
    {
        "file": "eval-gating.yml",
        "name": "Inner Loop Gating",
        "description": "Behavioral pytest and EvalHub gating on selected paths.",
    },
    {
        "file": "agent-deployment-test.yaml",
        "name": "QG4: Agent Deployment Integration Tests",
        "description": "Nightly OpenShift deploy, /health checks, and teardown.",
    },
)
RELEVANT_EVENTS = frozenset({"push", "schedule", "workflow_dispatch"})


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    name: str
    event: str
    head_branch: str
    status: str
    conclusion: str | None
    html_url: str
    created_at: str
    updated_at: str
    run_started_at: str | None

    @classmethod
    def from_api(cls, payload: dict) -> WorkflowRun:
        return cls(
            id=payload["id"],
            name=payload.get("name") or "workflow run",
            event=payload.get("event") or "unknown",
            head_branch=payload.get("head_branch") or "",
            status=payload.get("status") or "unknown",
            conclusion=payload.get("conclusion"),
            html_url=payload.get("html_url") or "",
            created_at=payload.get("created_at") or "",
            updated_at=payload.get("updated_at") or "",
            run_started_at=payload.get("run_started_at"),
        )


@dataclass(frozen=True)
class WorkflowSummary:
    workflow_file: str
    display_name: str
    description: str
    latest: WorkflowRun | None
    recent_runs: tuple[WorkflowRun, ...]
    pass_rate_7d: float | None
    total_runs_7d: int
    passed_runs_7d: int


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def duration_seconds(run: WorkflowRun) -> int | None:
    if not run.run_started_at or not run.updated_at:
        return None
    if run.status != "completed":
        return None
    start = parse_timestamp(run.run_started_at)
    end = parse_timestamp(run.updated_at)
    return max(int((end - start).total_seconds()), 0)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def is_relevant_run(run: WorkflowRun) -> bool:
    if run.event not in RELEVANT_EVENTS:
        return False
    if run.event == "schedule":
        return True
    return run.head_branch == "main"


def conclusion_label(conclusion: str | None, status: str) -> tuple[str, str]:
    if status != "completed":
        return ("In progress", "status-running")
    mapping = {
        "success": ("Pass", "status-pass"),
        "failure": ("Fail", "status-fail"),
        "cancelled": ("Cancelled", "status-neutral"),
        "skipped": ("Skipped", "status-neutral"),
        "timed_out": ("Timed out", "status-fail"),
        "action_required": ("Action required", "status-neutral"),
    }
    return mapping.get(conclusion or "", ("Unknown", "status-neutral"))


def compute_pass_rate(
    runs: list[WorkflowRun], *, days: int = 7
) -> tuple[float | None, int, int]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    scoped = [
        run
        for run in runs
        if is_relevant_run(run)
        and run.created_at
        and parse_timestamp(run.created_at) >= cutoff
        and run.status == "completed"
        and run.conclusion in {"success", "failure", "timed_out"}
    ]
    if not scoped:
        return None, 0, 0
    passed = sum(1 for run in scoped if run.conclusion == "success")
    return round(100 * passed / len(scoped), 1), len(scoped), passed


class GitHubActionsClient:
    def __init__(self, token: str, repository: str) -> None:
        self.repository = repository
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentic-starter-kits-ci-health-dashboard",
        }

    def _request(self, path: str, query: dict | None = None) -> dict:
        url = f"{API_ROOT}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API error {exc.code} for {path}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"GitHub API request failed for {path}: {exc.reason}"
            ) from exc

    def list_workflow_runs(
        self,
        workflow_file: str,
        *,
        per_page: int = 100,
        lookback_days: int = 7,
        max_pages: int = 10,
    ) -> list[WorkflowRun]:
        path = f"/repos/{self.repository}/actions/workflows/{workflow_file}/runs"
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        runs: list[WorkflowRun] = []
        for page in range(1, max_pages + 1):
            payload = self._request(path, {"per_page": per_page, "page": page})
            batch = [
                WorkflowRun.from_api(item) for item in payload.get("workflow_runs", [])
            ]
            if not batch:
                break
            runs.extend(batch)
            timestamps = [
                parse_timestamp(run.created_at) for run in batch if run.created_at
            ]
            if timestamps and min(timestamps) < cutoff:
                break
            if len(batch) < per_page:
                break
        return runs


def summarize_workflow(
    workflow: dict,
    runs: list[WorkflowRun],
) -> WorkflowSummary:
    relevant = sorted(
        (run for run in runs if is_relevant_run(run)),
        key=lambda run: run.created_at,
        reverse=True,
    )
    latest = relevant[0] if relevant else None
    pass_rate, total, passed = compute_pass_rate(runs)
    return WorkflowSummary(
        workflow_file=workflow["file"],
        display_name=workflow["name"],
        description=workflow["description"],
        latest=latest,
        recent_runs=tuple(relevant[:5]),
        pass_rate_7d=pass_rate,
        total_runs_7d=total,
        passed_runs_7d=passed,
    )


def load_fixture(path: Path) -> dict[str, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            "Fixture root must be a JSON object keyed by workflow file name"
        )
    return payload


def summaries_from_fixture(path: Path) -> list[WorkflowSummary]:
    payload = load_fixture(path)
    summaries: list[WorkflowSummary] = []
    for workflow in WORKFLOWS:
        runs = [
            WorkflowRun.from_api(item) for item in payload.get(workflow["file"], [])
        ]
        summaries.append(summarize_workflow(workflow, runs))
    return summaries


def summaries_from_api(repository: str, token: str) -> list[WorkflowSummary]:
    client = GitHubActionsClient(token, repository)
    summaries: list[WorkflowSummary] = []
    for workflow in WORKFLOWS:
        runs = client.list_workflow_runs(workflow["file"])
        summaries.append(summarize_workflow(workflow, runs))
    return summaries


def render_workflow_card(summary: WorkflowSummary) -> str:
    latest = summary.latest
    if latest is None:
        body = "<p class='muted'>No recent runs on <code>main</code> or scheduled triggers.</p>"
    else:
        label, css_class = conclusion_label(latest.conclusion, latest.status)
        body = f"""
        <div class="metric-row">
          <span class="pill {css_class}">{html.escape(label)}</span>
          <span>{html.escape(latest.event)}</span>
          <span>{html.escape(format_duration(duration_seconds(latest)))}</span>
          <span>{html.escape(parse_timestamp(latest.created_at).strftime("%Y-%m-%d %H:%M UTC"))}</span>
        </div>
        <p><a href="{html.escape(latest.html_url, quote=True)}">Open latest run</a></p>
        """

    if summary.pass_rate_7d is None:
        rate_text = "No completed runs in the last 7 days"
    else:
        rate_text = (
            f"{summary.pass_rate_7d:.1f}% pass rate "
            f"({summary.passed_runs_7d}/{summary.total_runs_7d} runs)"
        )

    recent_rows = []
    for run in summary.recent_runs:
        label, css_class = conclusion_label(run.conclusion, run.status)
        recent_rows.append(
            "<tr>"
            f"<td><span class='pill {css_class}'>{html.escape(label)}</span></td>"
            f"<td>{html.escape(run.event)}</td>"
            f"<td>{html.escape(parse_timestamp(run.created_at).strftime('%Y-%m-%d %H:%M'))}</td>"
            f"<td><a href='{html.escape(run.html_url, quote=True)}'>#{run.id}</a></td>"
            "</tr>"
        )
    recent_table = (
        "<table><thead><tr><th>Result</th><th>Event</th><th>Started</th><th>Run</th></tr></thead>"
        f"<tbody>{''.join(recent_rows)}</tbody></table>"
        if recent_rows
        else "<p class='muted'>No recent qualifying runs.</p>"
    )

    return f"""
    <section class="card">
      <h2>{html.escape(summary.display_name)}</h2>
      <p class="muted">{html.escape(summary.description)}</p>
      <p><strong>7-day health:</strong> {html.escape(rate_text)}</p>
      <h3>Latest qualifying run</h3>
      {body}
      <h3>Recent runs</h3>
      {recent_table}
    </section>
    """


def render_page(
    summaries: list[WorkflowSummary],
    *,
    repository: str,
    generated_at: datetime,
    data_source: str,
) -> str:
    cards = "\n".join(render_workflow_card(summary) for summary in summaries)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CI Health Dashboard</title>
  <style>
  :root {{
    color-scheme: light dark;
    --bg: #0f172a;
    --panel: #111827;
    --text: #e5e7eb;
    --muted: #9ca3af;
    --border: #1f2937;
    --pass: #166534;
    --fail: #991b1b;
    --neutral: #374151;
    --running: #1d4ed8;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f8fafc;
      --panel: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --border: #e2e8f0;
      --pass: #dcfce7;
      --fail: #fee2e2;
      --neutral: #e2e8f0;
      --running: #dbeafe;
    }}
  }}
  body {{
    margin: 0;
    font-family: Inter, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  main {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 2rem 1.25rem 3rem;
  }}
  h1, h2, h3 {{ margin-top: 0; }}
  .hero, .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
  }}
  .muted {{ color: var(--muted); }}
  .grid {{
    display: grid;
    gap: 1rem;
  }}
  .metric-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.75rem;
    margin: 0.75rem 0;
  }}
  .pill {{
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
  }}
  .status-pass {{ background: var(--pass); }}
  .status-fail {{ background: var(--fail); }}
  .status-neutral {{ background: var(--neutral); }}
  .status-running {{ background: var(--running); }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.95rem;
  }}
  th, td {{
    border-bottom: 1px solid var(--border);
    padding: 0.5rem 0.25rem;
    text-align: left;
  }}
  a {{ color: #60a5fa; }}
  code {{
    background: rgba(148, 163, 184, 0.15);
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
  }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>agentic-starter-kits CI Health</h1>
      <p class="muted">
        Daily summary for QG8 in-scope workflows on <code>main</code> and scheduled runs.
      </p>
      <p><strong>Repository:</strong> <code>{html.escape(repository)}</code></p>
      <p><strong>Last updated:</strong> {html.escape(generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))}</p>
      <p><strong>Data source:</strong> {html.escape(data_source)}</p>
    </section>
    <div class="grid">
      {cards}
    </div>
  </main>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("site/index.html"),
        help="Path to write the generated HTML file",
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/repo for live GitHub API queries",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub token with actions:read",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional fixture JSON for offline generation and tests",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generated_at = datetime.now(UTC)

    if args.input:
        summaries = summaries_from_fixture(args.input)
        repository = args.repository or "red-hat-data-services/agentic-starter-kits"
        data_source = f"fixture: {args.input.as_posix()}"
    else:
        if not args.repository:
            print(
                "error: --repository or GITHUB_REPOSITORY is required", file=sys.stderr
            )
            return 1
        if not args.token:
            print("error: --token or GITHUB_TOKEN is required", file=sys.stderr)
            return 1
        summaries = summaries_from_api(args.repository, args.token)
        repository = args.repository
        data_source = "GitHub Actions API (main + scheduled/workflow_dispatch runs)"

    page = render_page(
        summaries,
        repository=repository,
        generated_at=generated_at,
        data_source=data_source,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
