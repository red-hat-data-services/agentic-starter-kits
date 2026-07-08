from __future__ import annotations

import os
import time

import pytest
import requests


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    url = f"{route_url}/.well-known/agent-card.json"
    verify = os.getenv("CLUSTER_CA_BUNDLE", False)
    last_exc = None
    for attempt in range(12):
        try:
            resp = requests.get(url, timeout=30, verify=verify)
            if resp.status_code == 200:
                card = resp.json()
                assert "name" in card, "Agent card missing 'name' field"
                return
        except requests.RequestException as exc:
            last_exc = exc
        time.sleep(5.0)
    pytest.fail(
        f"Agent card not available after 12 retries: {last_exc or resp.status_code}"
    )


@pytest.mark.integration
def test_all_deployments_healthy(all_routes):
    """Verify every deployment in the multi-component agent is healthy."""
    assert all_routes, "No routes discovered — deployment may have failed"
    verify = os.getenv("CLUSTER_CA_BUNDLE", False)
    for name, route_url in all_routes.items():
        url = f"{route_url}/.well-known/agent-card.json"
        last_exc = None
        for attempt in range(12):
            try:
                resp = requests.get(url, timeout=30, verify=verify)
                if resp.status_code == 200:
                    break
            except requests.RequestException as exc:
                last_exc = exc
            time.sleep(5.0)
        else:
            pytest.fail(
                f"Deployment {name} health check failed after 12 retries: "
                f"{last_exc or resp.status_code}"
            )
