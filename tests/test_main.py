"""Tests for the main FastAPI application module.

This module contains unit tests for the FastAPI app initialization, lifespan management,
and health check endpoint.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestApplicationInitialization:
    """Test suite for FastAPI application initialization."""

    def test_app_initialization_success(self) -> None:
        """Test successful application initialization."""
        from src.main import app

        assert app is not None
        assert app.title == "EM_B_V1 Knowledge Graph Chatbot"
        assert app.version == "0.1.0"

    def test_app_has_routers(self) -> None:
        """Test that the app includes all necessary routers."""
        from src.main import app

        # Check that routers are included
        routes = [route.path for route in app.routes]
        assert "/health" in routes
        assert "/chat/" in routes


class TestHealthCheckEndpoint:
    """Test suite for the health check endpoint."""

    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_health_check_success(self, mock_get_instance: MagicMock) -> None:
        """Test successful health check endpoint call.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance method.
        """
        mock_connection = MagicMock()
        mock_connection.verify_connectivity = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_health_check_response_type(self, mock_get_instance: MagicMock) -> None:
        """Test that health check returns correct response type.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance method.
        """
        mock_connection = MagicMock()
        mock_connection.verify_connectivity = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert isinstance(response.json(), dict)
        assert "status" in response.json()


class TestLifespanContext:
    """Test suite for the FastAPI lifespan context manager."""

    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_lifespan_startup(self, mock_get_instance: MagicMock) -> None:
        """Test lifespan startup phase initialization."""
        mock_connection = MagicMock()
        mock_connection.verify_connectivity = MagicMock()
        mock_connection.close = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        with TestClient(app):
            # Verify startup was called
            mock_get_instance.assert_called()
            mock_connection.verify_connectivity.assert_called()

    @patch("src.database.connection.Neo4jConnection.get_instance")
    def test_lifespan_shutdown(self, mock_get_instance: MagicMock) -> None:
        """Test lifespan shutdown phase connection closure."""
        mock_connection = MagicMock()
        mock_connection.verify_connectivity = MagicMock()
        mock_connection.close = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        with TestClient(app):
            pass

        # After context exit, connection.close() should have been called
        mock_connection.close.assert_called()


class TestApplicationMetadata:
    """Test suite for application metadata."""

    @patch("src.main.Neo4jConnection.get_instance")
    def test_app_title(self, mock_get_instance: MagicMock) -> None:
        """Test application title is set correctly.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance method.
        """
        mock_connection = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        assert app.title == "EM_B_V1 Knowledge Graph Chatbot"

    @patch("src.main.Neo4jConnection.get_instance")
    def test_app_description(self, mock_get_instance: MagicMock) -> None:
        """Test application description is set correctly.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance method.
        """
        mock_connection = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        assert "knowledge graph" in app.description.lower()

    @patch("src.main.Neo4jConnection.get_instance")
    def test_app_version(self, mock_get_instance: MagicMock) -> None:
        """Test application version is set correctly.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance method.
        """
        mock_connection = MagicMock()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        assert app.version == "0.1.0"
