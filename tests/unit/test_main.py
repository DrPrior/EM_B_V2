"""Unit tests for the FastAPI app entry point."""

import asyncio
import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app, lifespan

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
    # Use the OpenAPI schema rather than iterating app.routes: newer FastAPI
    # keeps included routers as lazy _IncludedRouter wrappers without a .path,
    # so the schema is the stable view of registered paths.
    paths = set(app.openapi()["paths"].keys())

    assert "/health" in paths
    assert "/chat/" in paths
    assert "/graph/nodes" in paths
    assert "/admin/ingest" in paths


def test_lifespan_configures_logging_then_logs_startup_failure(caplog) -> None:
    caplog.set_level(logging.INFO, logger="em_b")
    calls: list[str] = []

    with (
        patch("src.main.configure_logging", side_effect=lambda: calls.append("log")),
        patch(
            "src.main.Neo4jConnection.get_instance",
            side_effect=lambda: (
                calls.append("neo4j") or _raise(ValueError("no DB_URI"))
            ),
        ),
    ):
        with pytest.raises(ValueError):
            asyncio.run(_enter_lifespan())

    # Logging must be up before the first dependency can fail.
    assert calls == ["log", "neo4j"]
    (error,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error.name == "em_b.main"
    assert "Failed to initialize Neo4j connection" in error.getMessage()
    assert error.exc_info is not None


def _raise(exc: Exception) -> None:
    raise exc


async def _enter_lifespan() -> None:
    async with lifespan(app):
        pass
