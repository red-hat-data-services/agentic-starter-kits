from __future__ import annotations

import os
import time

import pytest
import requests


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    url = f"{route_url}/health"
    verify = os.getenv("CLUSTER_CA_BUNDLE", False)
    last_exc = None
    for attempt in range(12):
        try:
            resp = requests.get(url, timeout=30, verify=verify)
            if resp.status_code == 200:
                return
        except requests.RequestException as exc:
            last_exc = exc
        time.sleep(5.0)
    pytest.fail(f"Health endpoint not available after 12 retries: {last_exc or resp.status_code}")
