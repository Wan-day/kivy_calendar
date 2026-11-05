"""Tests for the FastAPI backend health endpoint."""

import pytest
from api.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Return a FastAPI test client for the app."""
    return TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    """The health endpoint should return a 200 with status ok."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
