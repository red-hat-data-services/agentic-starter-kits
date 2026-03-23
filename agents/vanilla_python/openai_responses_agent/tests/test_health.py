from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with a mocked agent."""
    with patch("main.get_agent_closure") as mock_closure:
        mock_closure.return_value = lambda: None
        from main import app

        yield TestClient(app)


def test_health_endpoint(client):
    """Test that /health returns 200 with expected fields."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "agent_initialized" in data
