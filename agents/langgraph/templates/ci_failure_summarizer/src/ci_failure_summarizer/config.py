"""Environment-backed configuration for the CI failure summarizer spike."""

from __future__ import annotations

from dataclasses import dataclass, replace
from os import getenv

QG4_WORKFLOW_FILE = "agent-deployment-test.yaml"
CI_DASHBOARD_URL = "https://red-hat-data-services.github.io/agentic-starter-kits/"


def normalize_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return base_url
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = normalized + "/v1"
    return normalized


@dataclass(frozen=True)
class SummarizerConfig:
    repository: str
    workflow_name: str
    slack_webhook_url: str | None
    github_token: str | None
    model_id: str | None
    base_url: str | None
    api_key: str | None
    workflow_file: str = QG4_WORKFLOW_FILE
    dashboard_url: str = CI_DASHBOARD_URL

    @classmethod
    def from_env(cls) -> SummarizerConfig:
        repository = getenv("GITHUB_REPOSITORY", "").strip()
        workflow_name = (
            getenv("GITHUB_WORKFLOW", "QG4: Agent Deployment Integration Tests").strip()
            or "QG4: Agent Deployment Integration Tests"
        )
        if not repository:
            raise ValueError("GITHUB_REPOSITORY is required")

        base_url = normalize_base_url(getenv("BASE_URL"))

        return cls(
            repository=repository,
            workflow_name=workflow_name,
            slack_webhook_url=(getenv("SLACK_WEBHOOK_URL") or "").strip() or None,
            github_token=(getenv("GITHUB_TOKEN") or "").strip() or None,
            model_id=getenv("MODEL_ID"),
            base_url=base_url,
            api_key=getenv("API_KEY"),
            workflow_file=(
                getenv("GITHUB_WORKFLOW_FILE", QG4_WORKFLOW_FILE).strip()
                or QG4_WORKFLOW_FILE
            ),
        )

    def without_slack_posting(self) -> SummarizerConfig:
        """Return a copy that skips Slack webhook delivery (dry-run / no-post mode)."""
        return replace(self, slack_webhook_url=None)
