#!/usr/bin/env python3
"""
Discover agents — scan agents/**/agent.yaml and emit metadata as JSON.

Walks the agents/ directory tree, parses every agent.yaml it finds,
extracts the fields needed for manifest generation, and prints a
sorted JSON array to stdout.

Usage:
    python discover_agents.py [REPO_ROOT]

    REPO_ROOT defaults to the current working directory.
"""

import json
import sys
from pathlib import Path

import yaml

REQUIRED_FIELDS = ("name", "displayName", "description", "framework")


def discover_agents(repo_root: str) -> list[dict]:
    """Find all agent.yaml files under agents/ and return their metadata."""
    root = Path(repo_root)
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return []

    agents = []
    for agent_yaml in sorted(agents_dir.rglob("agent.yaml")):
        try:
            with open(agent_yaml) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print(
                f"WARNING: skipping {agent_yaml} — invalid YAML: {exc}",
                file=sys.stderr,
            )
            continue
        if not isinstance(data, dict) or not all(data.get(k) for k in REQUIRED_FIELDS):
            print(
                f"WARNING: skipping {agent_yaml} — invalid structure or missing required fields",
                file=sys.stderr,
            )
            continue
        agent_dir = agent_yaml.parent
        agents.append(
            {
                "name": data["name"],
                "displayName": data["displayName"],
                "description": data["description"],
                "framework": data["framework"],
                "path": str(agent_dir.relative_to(root)),
            }
        )

    agents.sort(key=lambda a: a["name"])
    return agents


def main() -> None:
    repo_root = sys.argv[1] if len(sys.argv) > 1 else "."
    agents = discover_agents(repo_root)
    json.dump(agents, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
