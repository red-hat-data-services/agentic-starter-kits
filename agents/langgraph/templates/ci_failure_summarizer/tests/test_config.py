"""Tests for summarizer configuration helpers."""

from __future__ import annotations

from ci_failure_summarizer.config import SummarizerConfig


def test_without_slack_posting_clears_webhook_only():
    config = SummarizerConfig(
        repository="red-hat-data-services/agentic-starter-kits",
        workflow_name="QG4: Agent Deployment Integration Tests",
        slack_webhook_url="https://hooks.slack.com/services/test",
        github_token="ghp_test",
        model_id="test-model",
        base_url="http://localhost:8321/v1",
        api_key="test-key",
        workflow_file="agent-deployment-test.yaml",
    )

    dry_run = config.without_slack_posting()

    assert dry_run.slack_webhook_url is None
    assert dry_run.github_token == "ghp_test"
    assert dry_run.repository == config.repository
    assert dry_run.workflow_name == config.workflow_name
