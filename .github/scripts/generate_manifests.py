#!/usr/bin/env python3
"""
Generate OdhDocument manifests — template agent metadata into dashboard CRs.

Takes a JSON array of discovered agents (from discover_agents.py) and
generates OdhDocument YAML manifests, an OdhApplication manifest, and a
kustomization.yaml for the odh-dashboard repo.

Usage:
    python generate_manifests.py AGENTS_JSON OUTPUT_DIR VERSION [SHORT_URLS_JSON]

    AGENTS_JSON     — path to JSON file from discover_agents.py
    OUTPUT_DIR      — directory to write generated manifests
    VERSION         — RHOAI version (e.g., "3.6")
    SHORT_URLS_JSON — optional path to JSON file mapping agent name → red.ht URL
"""

import json
import sys
from pathlib import Path
from string import Template

UPSTREAM_REPO = "red-hat-data-services/agentic-starter-kits"

ODHDOCUMENT_TEMPLATE = Template("""\
apiVersion: dashboard.opendatahub.io/v1
kind: OdhDocument
metadata:
  name: $manifest_name
  annotations:
    opendatahub.io/categories: 'Agent Templates,Getting started'
spec:
  type: tutorial
  displayName: '$display_name'
  description: >-
    $description
  url: '$url'
  appName: agentic-starter-kits
""")

ODHAPPLICATION_TEMPLATE = Template("""\
apiVersion: dashboard.opendatahub.io/v1
kind: OdhApplication
metadata:
  name: agentic-starter-kits
  annotations:
    opendatahub.io/categories: 'Agent Templates,Getting started'
spec:
  img: >-
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" width="36" height="36">
      <rect x="2" y="2" width="32" height="32" rx="4" fill="#0066CC"/>
      <circle cx="12" cy="14" r="4" fill="white" opacity="0.9"/>
      <circle cx="24" cy="14" r="4" fill="white" opacity="0.9"/>
      <circle cx="18" cy="26" r="4" fill="white" opacity="0.9"/>
      <line x1="12" y1="14" x2="24" y2="14" stroke="white" stroke-width="1.5" opacity="0.6"/>
      <line x1="12" y1="14" x2="18" y2="26" stroke="white" stroke-width="1.5" opacity="0.6"/>
      <line x1="24" y1="14" x2="18" y2="26" stroke="white" stroke-width="1.5" opacity="0.6"/>
      <circle cx="12" cy="14" r="2" fill="#EE0000"/>
      <circle cx="24" cy="14" r="2" fill="#EE0000"/>
      <circle cx="18" cy="26" r="2" fill="#EE0000"/>
    </svg>
  displayName: Agentic Starter Kits
  support: community
  provider: Red Hat
  docsLink: ''
  getStartedLink: 'https://github.com/$upstream_repo#how-to-use-this-repository'
  quickStart: ''
  getStartedMarkDown: ''
  description: >-
    Production-ready agent templates for OpenShift AI featuring LangGraph,
    LlamaIndex, CrewAI, AutoGen, Langflow, Google ADK, A2A, and vanilla
    Python patterns.
  category: Self-managed
  hidden: true
""")

KUSTOMIZATION_TEMPLATE = Template("""\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
$resources
""")


def _fallback_url(agent_path: str, version: str) -> str:
    return f"https://github.com/{UPSTREAM_REPO}/tree/rhoai-{version}/{agent_path}"


def generate_manifests(
    agents: list[dict],
    output_dir: str,
    version: str,
    short_urls: dict[str, str] | None = None,
) -> list[str]:
    """Generate OdhDocument YAMLs, OdhApplication, and kustomization.yaml."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    short_urls = short_urls or {}
    generated = []

    app_filename = "agentic-starter-kits-app.yaml"
    app_content = ODHAPPLICATION_TEMPLATE.substitute(upstream_repo=UPSTREAM_REPO)
    (out / app_filename).write_text(app_content)
    generated.append(app_filename)

    for agent in sorted(agents, key=lambda a: a["name"]):
        manifest_name = f"agentic-starter-kits-{agent['name']}-tutorial"
        filename = f"{manifest_name}.yaml"
        url = short_urls.get(agent["name"], _fallback_url(agent["path"], version))
        content = ODHDOCUMENT_TEMPLATE.substitute(
            manifest_name=manifest_name,
            display_name=agent["displayName"].replace("'", "''"),
            description=agent["description"].replace("\n", "\n    "),
            url=url,
        )
        (out / filename).write_text(content)
        generated.append(filename)

    resource_lines = [f"  - {generated[0]}"]
    for f in sorted(generated[1:]):
        resource_lines.append(f"  - {f}")
    kust_content = KUSTOMIZATION_TEMPLATE.substitute(
        resources="\n".join(resource_lines)
    )
    (out / "kustomization.yaml").write_text(kust_content)
    generated.append("kustomization.yaml")

    return generated


def main() -> None:
    if len(sys.argv) < 4:
        print(
            f"Usage: {sys.argv[0]} AGENTS_JSON OUTPUT_DIR VERSION [SHORT_URLS_JSON]",
            file=sys.stderr,
        )
        sys.exit(1)

    agents_json_path = sys.argv[1]
    output_dir = sys.argv[2]
    version = sys.argv[3]

    with open(agents_json_path) as f:
        agents = json.load(f)

    short_urls = None
    if len(sys.argv) > 4:
        with open(sys.argv[4]) as f:
            short_urls = json.load(f)

    files = generate_manifests(agents, output_dir, version, short_urls)
    print(f"Generated {len(files)} files in {output_dir}:")
    for name in files:
        print(f"  {name}")


if __name__ == "__main__":
    main()
