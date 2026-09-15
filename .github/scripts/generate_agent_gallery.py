#!/usr/bin/env python3
"""
Generate a thin GitHub Pages homepage from agents/**/agent.yaml.

Each card links to the agent directory on GitHub. README bodies are not
rendered. Used by .github/workflows/ci-health-pages.yml.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_GITHUB_BASE = (
    "https://github.com/red-hat-data-services/agentic-starter-kits/tree/main"
)
DESCRIPTION_LIMIT = 165
MAX_LABELS = 4
SAFE_LOGO = re.compile(
    r"^data:image/(?:png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$"
)

CSS = """
:root {
  --rh-color-brand-red: #ee0000;
  --rh-color-brand-red-dark: #a60000;
  --rh-color-white: #ffffff;
  --rh-color-surface: #f2f2f2;
  --rh-color-text: #151515;
  --rh-color-muted: #707070;
  --rh-color-border: #c7c7c7;
  --rh-color-link: #0066cc;
  --rh-font-display: "Red Hat Display", "Red Hat Text", system-ui, sans-serif;
  --rh-font-text: "Red Hat Text", system-ui, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; }
html { color-scheme: light; }
body {
  margin: 0;
  background: var(--rh-color-surface);
  color: var(--rh-color-text);
  font-family: var(--rh-font-text);
  line-height: 1.5;
}
.skip-link {
  position: absolute;
  left: -999px;
  top: 0;
  background: var(--rh-color-white);
  color: var(--rh-color-text);
  padding: 0.5rem 0.75rem;
}
.skip-link:focus { left: 0.5rem; top: 0.5rem; z-index: 2; }
.masthead {
  border-top: 4px solid var(--rh-color-brand-red);
  background: var(--rh-color-white);
  border-bottom: 1px solid var(--rh-color-border);
}
.wrap {
  max-width: 72rem;
  margin: 0 auto;
  padding: 1.5rem 1.25rem;
}
.masthead .wrap { padding-bottom: 1rem; }
#gallery { padding-top: 1.25rem; padding-bottom: 2.5rem; }
h1 {
  font-family: var(--rh-font-display);
  font-weight: 700;
  font-size: 2rem;
  line-height: 1.2;
  margin: 0 0 0.75rem;
}
.lede { margin: 0 0 1rem; text-wrap: pretty; max-width: 52rem; }
.meta-links { display: flex; flex-wrap: wrap; gap: 0.75rem 1.25rem; margin: 0; padding: 0; list-style: none; }
a { color: var(--rh-color-link); }
a:hover { color: var(--rh-color-brand-red-dark); }
a:focus-visible, button:focus-visible, input:focus-visible {
  outline: 2px solid var(--rh-color-brand-red);
  outline-offset: 2px;
}
.toolbar { display: grid; gap: 0.65rem; margin: 1rem 0 0; }
.search-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.search-row label {
  font-weight: 500;
  white-space: nowrap;
  margin: 0;
}
input[type="search"] {
  font: inherit;
  flex: 1;
  min-width: 12rem;
  max-width: 28rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--rh-color-border);
  background: var(--rh-color-white);
}
.filter-row {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}
.filter-label {
  flex: 0 0 5.5rem;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--rh-color-muted);
  white-space: nowrap;
  padding-top: 0.25rem;
}
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; flex: 1; min-width: 0; }
button.chip {
  font: inherit;
  font-size: 0.9rem;
  padding: 0.2rem 0.7rem;
  border: 1px solid var(--rh-color-border);
  background: var(--rh-color-white);
  color: var(--rh-color-text);
  cursor: pointer;
  white-space: nowrap;
}
button.chip[aria-pressed="true"] {
  border-color: var(--rh-color-text);
  background: var(--rh-color-text);
  color: var(--rh-color-white);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16.5rem, 1fr));
  gap: 1rem;
}
@media (min-width: 64rem) {
  .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
.card {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 1rem;
  background: var(--rh-color-white);
  border: 1px solid var(--rh-color-border);
  color: inherit;
  text-decoration: none;
}
.card[hidden],
.empty[hidden] {
  display: none;
}
.card:hover { border-color: var(--rh-color-text); }
.card-top { display: flex; gap: 0.75rem; align-items: flex-start; margin-bottom: 0.5rem; }
.card-top > div { min-width: 0; flex: 1; }
.card-top img, .card-fallback {
  width: 2.5rem;
  height: 2.5rem;
  flex: 0 0 2.5rem;
  object-fit: contain;
  background: var(--rh-color-surface);
}
.card-fallback {
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 0.9rem;
}
.card h3 {
  font-family: var(--rh-font-display);
  font-size: 1.05rem;
  font-weight: 500;
  margin: 0;
}
.vendor, .kind, .cta { font-size: 0.85rem; color: var(--rh-color-muted); }
.vendor { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card p { margin: 0.35rem 0 0.75rem; flex: 1; }
.labels { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0 0 0.75rem; }
.labels span {
  font-size: 0.75rem;
  padding: 0.1rem 0.45rem;
  border: 1px solid var(--rh-color-border);
}
.cta { margin-top: auto; font-weight: 500; color: var(--rh-color-link); }
.empty { margin: 1rem 0; }
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}
"""

JS = """
(function () {
  const search = document.getElementById("kit-search");
  const cards = Array.from(document.querySelectorAll("[data-card]"));
  const chips = Array.from(document.querySelectorAll("[data-filter]"));
  const empty = document.getElementById("empty-state");
  let framework = "all";
  let kind = "all";

  function apply() {
    const q = (search.value || "").trim().toLowerCase();
    let visible = 0;
    for (const card of cards) {
      const hay = card.getAttribute("data-search") || "";
      const matchQ = !q || hay.indexOf(q) !== -1;
      const matchFw = framework === "all" || card.getAttribute("data-framework") === framework;
      const matchKind = kind === "all" || card.getAttribute("data-kind") === kind;
      const show = matchQ && matchFw && matchKind;
      card.hidden = !show;
      if (show) visible += 1;
    }
    empty.hidden = visible > 0;
  }

  search.addEventListener("input", apply);
  for (const btn of chips) {
    btn.addEventListener("click", function () {
      const group = btn.getAttribute("data-filter-group");
      const value = btn.getAttribute("data-filter");
      if (group === "framework") framework = value;
      if (group === "kind") kind = value;
      for (const other of chips) {
        if (other.getAttribute("data-filter-group") === group) {
          other.setAttribute("aria-pressed", other === btn ? "true" : "false");
        }
      }
      apply();
    });
  }
})();
"""


@dataclass(frozen=True)
class AgentRecord:
    name: str
    display_name: str
    framework: str
    description: str
    labels: tuple[str, ...]
    logo: str | None
    rel_path: str
    kind: str
    github_url: str

    @property
    def search_text(self) -> str:
        parts = [
            self.display_name,
            self.description,
            self.framework,
            self.kind,
            self.name,
            *self.labels,
        ]
        return " ".join(parts).lower()


def _is_worktree(path: Path) -> bool:
    parts = path.parts
    return ".claude" in parts and "worktrees" in parts


def _kind_from_path(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if "examples" in parts:
        return "example"
    if "templates" in parts:
        return "template"
    return "other"


def _clamp(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _labels(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    labels: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
    return tuple(labels)


def _safe_logo(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = "".join(raw.split())
    if SAFE_LOGO.match(value) and "<script" not in value.lower():
        return value
    return None


def collect_agents(
    repo_root: Path,
    *,
    github_base: str = DEFAULT_GITHUB_BASE,
) -> list[AgentRecord]:
    """Walk agents/**/agent.yaml; skip worktrees and kits without displayName."""
    root = Path(repo_root)
    agents_dir = root / "agents"
    records: list[AgentRecord] = []
    if not agents_dir.is_dir():
        return records

    for agent_yaml in sorted(agents_dir.rglob("agent.yaml")):
        if _is_worktree(agent_yaml):
            print(f"WARNING: skipping worktree {agent_yaml}", file=sys.stderr)
            continue
        try:
            data = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            print(f"WARNING: skipping {agent_yaml} — {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print(f"WARNING: skipping {agent_yaml} — not a mapping", file=sys.stderr)
            continue
        display_name = data.get("displayName")
        if not isinstance(display_name, str) or not display_name.strip():
            print(
                f"WARNING: skipping {agent_yaml} — missing displayName",
                file=sys.stderr,
            )
            continue
        framework = data.get("framework")
        if not isinstance(framework, str) or not framework.strip():
            print(
                f"WARNING: skipping {agent_yaml} — missing framework",
                file=sys.stderr,
            )
            continue
        description = data.get("description")
        if not isinstance(description, str):
            description = ""
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            name = agent_yaml.parent.name
        rel_path = agent_yaml.parent.relative_to(root).as_posix()
        records.append(
            AgentRecord(
                name=name.strip(),
                display_name=display_name.strip(),
                framework=framework.strip(),
                description=_clamp(description),
                labels=_labels(data.get("labels")),
                logo=_safe_logo(data.get("logo")),
                rel_path=rel_path,
                kind=_kind_from_path(rel_path),
                github_url=f"{github_base.rstrip('/')}/{rel_path}",
            )
        )

    records.sort(key=lambda item: item.display_name.lower())
    return records


def _chip(group: str, value: str, label: str, *, pressed: bool) -> str:
    return (
        f'<button type="button" class="chip" data-filter-group="{html.escape(group)}" '
        f'data-filter="{html.escape(value)}" aria-pressed="{str(pressed).lower()}">'
        f"{html.escape(label)}</button>"
    )


def _logo_html(agent: AgentRecord) -> str:
    if agent.logo:
        return f'<img src="{html.escape(agent.logo, quote=True)}" alt="" width="40" height="40">'
    initial = html.escape(agent.framework[:1].upper() or "?")
    return f'<span class="card-fallback" aria-hidden="true">{initial}</span>'


def _labels_html(labels: Sequence[str]) -> str:
    if not labels:
        return ""
    shown = labels[:MAX_LABELS]
    extra = len(labels) - len(shown)
    bits = [f"<span>{html.escape(label)}</span>" for label in shown]
    if extra:
        bits.append(f"<span>+{extra}</span>")
    return f'<div class="labels">{"".join(bits)}</div>'


def _card_html(agent: AgentRecord) -> str:
    search = html.escape(agent.search_text, quote=True)
    href = html.escape(agent.github_url, quote=True)
    title = html.escape(agent.display_name)
    vendor = html.escape(agent.framework)
    kind = html.escape(agent.kind)
    body = html.escape(agent.description)
    return f"""
<a class="card" data-card data-framework="{vendor}" data-kind="{kind}" data-search="{search}" href="{href}">
  <div class="card-top">
    {_logo_html(agent)}
    <div>
      <h3>{title}</h3>
      <div class="vendor">{vendor}</div>
    </div>
  </div>
  <p>{body}</p>
  {_labels_html(agent.labels)}
  <div class="kind">{kind}</div>
  <div class="cta">View on GitHub</div>
</a>
"""


def render_gallery(agents: Sequence[AgentRecord]) -> str:
    frameworks = sorted({agent.framework for agent in agents}, key=str.lower)
    framework_chips = [_chip("framework", "all", "All", pressed=True)]
    framework_chips.extend(
        _chip("framework", name, name, pressed=False) for name in frameworks
    )
    kind_chips = [
        _chip("kind", "all", "All", pressed=True),
        _chip("kind", "template", "Templates", pressed=False),
        _chip("kind", "example", "Examples", pressed=False),
    ]
    cards = "".join(_card_html(agent) for agent in agents)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agentic starter kits</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;700&family=Red+Hat+Text:wght@400;500&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>
  <a class="skip-link" href="#gallery">Skip to kits</a>
  <header class="masthead">
    <div class="wrap">
      <h1>Agentic starter kits</h1>
      <p class="lede">
        Deployment-ready templates for AI agents on Red Hat OpenShift AI. Each kit
        is self-contained with docs, a container build, and Helm charts so you can
        run locally and deploy without stitching together boilerplate. Open a kit’s
        GitHub README for setup and deployment steps.
      </p>
      <ul class="meta-links">
        <li><a href="https://github.com/red-hat-data-services/agentic-starter-kits">GitHub repository</a></li>
        <li><a href="ci-health/">CI health</a></li>
      </ul>
      <div class="toolbar">
        <div class="search-row">
          <label for="kit-search">Search</label>
          <input type="search" id="kit-search" placeholder="Name, framework, or label">
        </div>
        <div class="filter-row">
          <span class="filter-label">Framework</span>
          <div class="chips" role="group" aria-label="Filter by framework">
            {"".join(framework_chips)}
          </div>
        </div>
        <div class="filter-row">
          <span class="filter-label">Type</span>
          <div class="chips" role="group" aria-label="Filter by type">
            {"".join(kind_chips)}
          </div>
        </div>
      </div>
    </div>
  </header>
  <main class="wrap" id="gallery">
    <p class="empty" id="empty-state" hidden>No kits match. Clear filters.</p>
    <div class="grid">{cards}</div>
  </main>
  <script>{JS}</script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root that contains agents/",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("site/index.html"),
        help="Path to write the generated HTML file",
    )
    parser.add_argument(
        "--github-base",
        default=DEFAULT_GITHUB_BASE,
        help="GitHub tree URL prefix (no trailing slash required)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agents = collect_agents(args.repo_root, github_base=args.github_base)
    page = render_gallery(agents)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(f"Wrote {args.output} ({len(agents)} kits)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
