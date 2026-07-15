import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with the agent global set to a mock factory."""
    import main

    original = main.get_agent
    main.get_agent = lambda: None
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c
    main.get_agent = original


def test_health_endpoint(client):
    """Test that /health returns 200 with expected fields."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "agent_initialized" in data
