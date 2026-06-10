"""Tests for the graph router module."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestGraphRouter:
    """Test suite for the graph router endpoints."""

    def _setup_mocks(self):
        """Helper to setup session and connection mocks.

        Returns:
            A tuple of (mock_session, mock_connection).
        """
        mock_session = MagicMock()
        
        def session_generator():
            yield mock_session
        
        connection = MagicMock()
        connection.get_session_dependency = session_generator
        return mock_session, connection

    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_get_nodes_success(
        self, mock_get_instance: MagicMock
    ) -> None:
        """Test successful retrieval of nodes."""
        mock_session, mock_connection = self._setup_mocks()
        mock_get_instance.return_value = mock_connection
        mock_session.execute_read.return_value = [
            {"id": "1", "labels": ["Concept"], "props": {"name": "Emergency"}}
        ]

        from src.main import app
        client = TestClient(app)
        response = client.get("/graph/nodes")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["element_id"] == "1"
        assert "Concept" in data[0]["labels"]

    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_get_node_by_id_not_found(
        self, mock_get_instance: MagicMock
    ) -> None:
        """Test retrieving a node that does not exist."""
        mock_session, mock_connection = self._setup_mocks()
        mock_get_instance.return_value = mock_connection
        mock_session.execute_read.return_value = None  # Node not found

        from src.main import app
        client = TestClient(app)
        response = client.get("/graph/nodes/invalid_id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("src.routers.graph.generate_embedding")
    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_vector_search_success(
        self,
        mock_get_instance: MagicMock,
        mock_generate_embedding: MagicMock,
    ) -> None:
        """Test successful vector search."""
        mock_session, mock_connection = self._setup_mocks()
        mock_get_instance.return_value = mock_connection
        mock_generate_embedding.return_value = [0.1, 0.2, 0.3]
        mock_session.execute_read.return_value = [
            {"id": "1", "labels": ["Chunk"], "props": {"text": "hello context"}, "score": 0.95}
        ]

        from src.main import app
        client = TestClient(app)
        response = client.post(
            "/graph/search",
            json={"query": "hello world", "top_k": 3}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "hello world"
        assert data["total_results"] == 1
        assert data["results"][0]["element_id"] == "1"
        
        # Verify the embedding generation was called with the right text
        mock_generate_embedding.assert_called_once_with("hello world")

    @patch("src.routers.graph.generate_embedding")
    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_vector_search_embedding_failure(
        self,
        mock_get_instance: MagicMock,
        mock_generate_embedding: MagicMock,
    ) -> None:
        """Test vector search handles embedding service failures."""
        mock_session, mock_connection = self._setup_mocks()
        mock_get_instance.return_value = mock_connection
        mock_generate_embedding.side_effect = Exception("Ollama is down")

        from src.main import app
        client = TestClient(app)
        response = client.post("/graph/search", json={"query": "test"})

        assert response.status_code == 500
        assert "Failed to generate embedding" in response.json()["detail"]
