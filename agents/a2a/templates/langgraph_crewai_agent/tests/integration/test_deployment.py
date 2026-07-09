from __future__ import annotations

import pytest
from integration.utils import health_check

_AGENT_CARD_FIELDS = (
    "name",
    "supportedInterfaces",
    "version",
    "capabilities",
    "skills",
)


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    card = health_check(
        f"{route_url}/.well-known/agent-card.json", retries=12, backoff=5.0
    )

    for field in _AGENT_CARD_FIELDS:
        assert field in card, f"Agent card missing '{field}' field"


@pytest.mark.integration
def test_all_deployments_healthy(all_routes):
    """Verify every deployment in the multi-component agent is healthy."""
    assert all_routes, "No routes discovered — deployment may have failed"
    cards = {}
    for name, route_url in all_routes.items():
        card = health_check(
            f"{route_url}/.well-known/agent-card.json", retries=12, backoff=5.0
        )
        assert "name" in card, f"Deployment {name}: agent card missing 'name' field"
        cards[name] = card

    names = [c["name"] for c in cards.values()]
    assert len(set(names)) == len(names), (
        f"Expected distinct agent names per deployment, got: {names}"
    )
