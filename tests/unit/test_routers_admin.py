"""Unit tests for the admin ingestion router (pipeline + Neo4j mocked)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.routers import admin as admin_router

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    # Plain instantiation skips the lifespan handler (no real Neo4j connection).
    app.dependency_overrides[admin_router.get_db_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ingest_success(client: TestClient) -> None:
    stats = {
        "files_processed": 3,
        "chunks_created": 12,
        "embeddings_stored": 12,
        "errors": 0,
    }
    with patch.object(admin_router, "ingest_project_data", return_value=stats):
        resp = client.post("/admin/ingest", json={"data_root": "/app/project_data"})

    assert resp.status_code == 200
    assert resp.json() == stats


def test_ingest_uses_default_body(client: TestClient) -> None:
    stats = {
        "files_processed": 0,
        "chunks_created": 0,
        "embeddings_stored": 0,
        "errors": 0,
    }
    with patch.object(
        admin_router, "ingest_project_data", return_value=stats
    ) as mock_ingest:
        resp = client.post("/admin/ingest")

    assert resp.status_code == 200
    # Default data_root is applied when no body is sent.
    _, kwargs = mock_ingest.call_args
    assert kwargs["data_root"] == "/app/project_data"


def test_ingest_failure_returns_500(client: TestClient) -> None:
    with patch.object(
        admin_router, "ingest_project_data", side_effect=RuntimeError("disk full")
    ):
        resp = client.post("/admin/ingest")

    assert resp.status_code == 500
