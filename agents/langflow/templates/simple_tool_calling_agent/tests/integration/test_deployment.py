from __future__ import annotations

import pytest
from integration.utils import health_check


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    result = health_check(f"{deployed_agent}/health_check", retries=12, backoff=5.0)
    assert result["status"] == "ok"
