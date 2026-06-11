"""Unit tests for the graph router (Neo4j + embeddings mocked)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.routers import graph as graph_router

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def client(mock_session):
    # Plain instantiation skips the lifespan handler (no real Neo4j connection).
    app.dependency_overrides[graph_router.get_session] = lambda: mock_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_nodes_returns_list(client: TestClient, mock_session) -> None:
    mock_session.execute_read.return_value = [
        {"id": "4:a", "labels": ["Concept"], "props": {"name": "ICS"}},
        {"id": "4:b", "labels": ["Document"], "props": {"filename": "f.pdf"}},
    ]

    resp = client.get("/graph/nodes")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["element_id"] == "4:a"
    assert body[0]["properties"] == {"name": "ICS"}


def test_get_node_by_id_found(client: TestClient, mock_session) -> None:
    mock_session.execute_read.return_value = {
        "id": "4:a",
        "labels": ["Concept"],
        "props": {"name": "ICS"},
    }

    resp = client.get("/graph/nodes/4:a")

    assert resp.status_code == 200
    assert resp.json()["element_id"] == "4:a"


def test_get_node_by_id_not_found(client: TestClient, mock_session) -> None:
    mock_session.execute_read.return_value = None

    resp = client.get("/graph/nodes/missing")

    assert resp.status_code == 404


def test_search_empty_query_rejected(client: TestClient) -> None:
    resp = client.get("/graph/search", params={"q": "   "})

    assert resp.status_code == 400


def test_search_returns_results(client: TestClient, mock_session) -> None:
    mock_session.execute_read.return_value = [
        {"id": "4:a", "labels": ["Concept"], "props": {"name": "ICS"}},
    ]

    resp = client.get("/graph/search", params={"q": "ICS"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "ICS"
    assert body["total_results"] == 1


def test_vector_search_returns_results(client: TestClient, mock_session) -> None:
    mock_session.execute_read.return_value = [
        {"id": "4:c", "labels": ["Chunk"], "props": {"text": "hello"}},
    ]

    with patch.object(
        graph_router, "generate_embedding", return_value=[0.1] * 2560
    ):
        resp = client.post("/graph/search", json={"query": "hello", "top_k": 3})

    assert resp.status_code == 200
    assert resp.json()["total_results"] == 1


def test_vector_search_embedding_failure_returns_500(
    client: TestClient, mock_session
) -> None:
    with patch.object(
        graph_router, "generate_embedding", side_effect=RuntimeError("ollama down")
    ):
        resp = client.post("/graph/search", json={"query": "hello"})

    assert resp.status_code == 500
