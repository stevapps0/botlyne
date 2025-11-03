"""Test health check endpoint."""
from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Test health check endpoint returns correct response."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "message" in data


def test_root_endpoint(client: TestClient):
    """Test root endpoint returns API information."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "description" in data
    assert "docs" in data
    assert "health" in data