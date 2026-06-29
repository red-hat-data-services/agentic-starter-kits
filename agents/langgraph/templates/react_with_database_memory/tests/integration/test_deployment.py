from __future__ import annotations

import pytest
from integration.utils import health_check


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    result = health_check(f"{route_url}/health", retries=12, backoff=5.0)

    assert result["status"] == "healthy"
    assert result["agent_initialized"] is True
    assert result["database_connected"] is True
