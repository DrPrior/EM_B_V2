"""Unit tests for the FastAPI app entry point."""

import pytest
from fastapi.testclient import TestClient

from src.main import app

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    # Plain instantiation skips the lifespan handler (no real Neo4j connection).
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_routers_are_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/health" in paths
    assert "/chat/" in paths
    assert "/graph/nodes" in paths
    assert "/admin/ingest" in paths
