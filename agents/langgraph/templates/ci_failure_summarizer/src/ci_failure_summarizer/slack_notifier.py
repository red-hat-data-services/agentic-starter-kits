"""Slack incoming webhook notifier for triage summaries."""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

from ci_failure_summarizer.models import FailureRecord, WorkflowRun

logger = logging.getLogger(__name__)

_SLACK_WEBHOOK_RE = re.compile(r"https://hooks\.slack\.com/\S+")


def sanitize_slack_error(
    exc: BaseException,
    *,
    webhook_url: str | None = None,
) -> str:
    """Return a safe Slack delivery error without leaking webhook URLs."""
    message = str(exc).strip()
    if webhook_url and webhook_url in message:
        message = message.replace(webhook_url, "<redacted-webhook-url>")
    message = _SLACK_WEBHOOK_RE.sub("<redacted-webhook-url>", message)
    if isinstance(exc, requests.RequestException):
        return "Slack delivery failed: network error contacting webhook"
    if message:
        return f"Slack delivery failed: {message}"
    return "Slack delivery failed"


def build_slack_payload(
    *,
    repository: str,
    run: WorkflowRun,
    summary_text: str,
    failures: list[FailureRecord],
    dashboard_url: str,
) -> dict[str, Any]:
    failed_jobs = sorted({failure.job_name for failure in failures})
    if failed_jobs:
        if len(failed_jobs) <= 10:
            failed_jobs_text = "\n".join(f"- `{name}`" for name in failed_jobs)
        else:
            shown = failed_jobs[:10]
            failed_jobs_text = "\n".join(f"- `{name}`" for name in shown)
            failed_jobs_text += f"\n- ... and {len(failed_jobs) - 10} more"
    else:
        failed_jobs_text = "- Job details unavailable"

    fallback = f"CI Triage Summary: {run.name} on {run.head_branch}"
    return {
        "text": fallback,
        "attachments": [
            {
                "color": "#5b21b6",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"CI Triage Summary: {run.name}",
                            "emoji": True,
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Workflow*\n{run.name}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Event*\n{run.event}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Ref*\n{run.head_branch}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Repository*\n`{repository}`",
                            },
                        ],
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Failed jobs*\n{failed_jobs_text}",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": summary_text,
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"<{run.html_url}|View workflow run> | "
                                f"<{dashboard_url}|View CI dashboard>"
                            ),
                        },
                    },
                ],
            }
        ],
    }


def post_summary(
    *,
    webhook_url: str,
    payload: dict[str, Any],
    timeout: int = 15,
) -> None:
    try:
        response = requests.post(webhook_url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(sanitize_slack_error(exc, webhook_url=webhook_url)) from exc
    if response.status_code >= 400:
        raise RuntimeError(
            f"Slack webhook returned HTTP {response.status_code}: {response.text}"
        )
    logger.info("Posted CI triage summary to Slack")


def maybe_post_summary(
    *,
    webhook_url: str | None,
    payload: dict[str, Any],
) -> tuple[bool, str | None]:
    if not webhook_url:
        return False, "SLACK_WEBHOOK_URL is not configured"
    try:
        post_summary(webhook_url=webhook_url, payload=payload)
    except Exception as exc:
        safe_message = sanitize_slack_error(exc, webhook_url=webhook_url)
        logger.error("%s", safe_message)
        return False, safe_message
    return True, None
