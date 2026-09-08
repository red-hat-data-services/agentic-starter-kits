#!/usr/bin/env python3
"""Manually trigger CI failure summarization without the HTTP server."""

from __future__ import annotations

import argparse
import json

from ci_failure_summarizer.config import SummarizerConfig
from ci_failure_summarizer.incident_store import IncidentStore
from ci_failure_summarizer.orchestrator import SummarizerOrchestrator
from ci_failure_summarizer.utils import get_database_uri
from dotenv import load_dotenv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Optional workflow run id (defaults to latest QG4 run)",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="Build the summary without posting to Slack",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    config = SummarizerConfig.from_env()
    if args.no_slack:
        config = config.without_slack_posting()

    store = IncidentStore(get_database_uri())
    store.setup()
    orchestrator = SummarizerOrchestrator(config=config, incident_store=store)
    result = orchestrator.run(run_id=args.run_id)

    print(result.summary_text)
    print()
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "run_url": result.run_url,
                "workflow_name": result.workflow_name,
                "failure_count": len(result.failures),
                "slack_posted": result.slack_posted,
                "slack_skipped_reason": result.slack_skipped_reason,
                "logs_available": result.logs_available,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
