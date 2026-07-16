"""Tests for summarize API contract."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import SummarizeRequest, SummarizeResponse


class TestSummarizeModels:
    def test_summarize_request_defaults(self):
        req = SummarizeRequest()
        assert req.run_id is None
        assert req.post_to_slack is True

    def test_summarize_response_shape(self):
        resp = SummarizeResponse(
            run_id=1,
            run_url="https://example.test/run/1",
            workflow_name="QG4: Agent Deployment Integration Tests",
            failures=[],
            summary_text="no failures",
            slack_posted=False,
        )
        assert resp.logs_available is False
