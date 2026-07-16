"""LLM summarization for grouped CI failures."""

from __future__ import annotations

import json
from textwrap import dedent

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ci_failure_summarizer.config import SummarizerConfig
from ci_failure_summarizer.models import FailureRecord, Incident, WorkflowRun


SYSTEM_PROMPT = dedent(
    """
    You are a CI triage assistant for the agentic-starter-kits repository.
    Produce a compact Slack-ready summary for grouped GitHub Actions failures.

    Requirements:
    - Cover impacted workflow/run, failed jobs/step areas, likely cause or a
      confidence-limited observation when logs are unavailable, and recommended
      next steps.
    - Recommendations only: do not claim remediation was executed.
    - When logs are unavailable, state that inference is metadata-only.
    - Keep the response under 350 words.
    - Use short markdown sections with bullet lists where helpful.
    """
).strip()


def _serialize_failures(
    run: WorkflowRun,
    failures: list[FailureRecord],
    incidents: list[Incident],
) -> str:
    incident_by_fp = {incident.fingerprint: incident for incident in incidents}
    payload = {
        "workflow": run.name,
        "run_id": run.id,
        "run_url": run.html_url,
        "event": run.event,
        "branch": run.head_branch,
        "conclusion": run.conclusion,
        "failures": [
            {
                "job": failure.job_name,
                "failed_step": failure.failed_step,
                "fingerprint": failure.fingerprint,
                "qg_label": failure.qg_label,
                "failure_area": failure.metadata.get("failure_area"),
                "logs_available": failure.logs_available,
                "log_excerpt": failure.log_excerpt,
                "occurrence_count": incident_by_fp[failure.fingerprint].occurrence_count
                if failure.fingerprint in incident_by_fp
                else 1,
            }
            for failure in failures
        ],
    }
    return json.dumps(payload, indent=2)


def compose_summary(
    *,
    config: SummarizerConfig,
    run: WorkflowRun,
    failures: list[FailureRecord],
    incidents: list[Incident],
) -> str:
    if not failures:
        return (
            f"No failed jobs found for workflow run #{run.id} "
            f"({run.html_url})."
        )

    if not config.base_url or not config.model_id:
        return compose_fallback_summary(run=run, failures=failures, incidents=incidents)

    chat = ChatOpenAI(
        model=config.model_id,
        temperature=0.1,
        api_key=config.api_key,
        base_url=config.base_url,
    )
    user_prompt = dedent(
        f"""
        Summarize these grouped CI failures for Slack triage:

        {_serialize_failures(run, failures, incidents)}
        """
    ).strip()
    response = chat.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )
    content = response.content
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def compose_fallback_summary(
    *,
    run: WorkflowRun,
    failures: list[FailureRecord],
    incidents: list[Incident],
) -> str:
    incident_by_fp = {incident.fingerprint: incident for incident in incidents}
    lines = [
        f"*CI Triage Summary* — {run.name}",
        f"*Run:* <{run.html_url}|#{run.id}> ({run.event} on `{run.head_branch}`)",
        "",
        "*Failed jobs / step areas*",
    ]
    for failure in failures:
        step = failure.failed_step or "unknown step"
        area = failure.metadata.get("failure_area")
        area_suffix = f" [{area}]" if area else ""
        incident = incident_by_fp.get(failure.fingerprint)
        count = incident.occurrence_count if incident else 1
        lines.append(
            f"- `{failure.job_name}` failed at `{step}`{area_suffix} "
            f"(fingerprint `{failure.fingerprint}`, seen {count}x)"
        )

    any_logs = any(failure.logs_available for failure in failures)
    lines.extend(
        [
            "",
            "*Likely cause*",
            (
                "- Log excerpts were available for at least one failed job; "
                "review run details for root cause."
                if any_logs
                else "- Job logs were unavailable without authenticated access; "
                "inference is limited to workflow/job/step metadata."
            ),
            "",
            "*Recommended next steps*",
            "- Open the workflow run and inspect failed matrix jobs.",
            "- Compare against recent occurrences of the same fingerprint in PostgreSQL.",
            "- Escalate to @aaet-tooling-experience if the failure is new or recurring.",
        ]
    )
    return "\n".join(lines)
