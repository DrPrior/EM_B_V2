"""Unit tests for the Neo4j connection manager (driver mocked)."""

from unittest.mock import MagicMock, patch

import pytest

import src.database.connection as connection_module
from src.database.connection import Neo4jConnection

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure each test starts with no cached singleton instance."""
    Neo4jConnection._instance = None
    yield
    Neo4jConnection._instance = None


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEO4J_AUTH", "neo4j/password")
    monkeypatch.setenv("DB_URI", "bolt://neo4j:7687")


def test_missing_auth_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_AUTH", raising=False)
    monkeypatch.setenv("DB_URI", "bolt://neo4j:7687")

    with pytest.raises(ValueError, match="NEO4J_AUTH"):
        Neo4jConnection()


def test_missing_uri_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_AUTH", "neo4j/password")
    monkeypatch.delenv("DB_URI", raising=False)

    with pytest.raises(ValueError, match="DB_URI"):
        Neo4jConnection()


def test_bad_auth_format_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_AUTH", "noslash")
    monkeypatch.setenv("DB_URI", "bolt://neo4j:7687")

    with patch.object(connection_module, "GraphDatabase"):
        with pytest.raises(ValueError, match="format is invalid"):
            Neo4jConnection()


def test_get_instance_is_singleton(valid_env) -> None:
    with patch.object(connection_module, "GraphDatabase"):
        first = Neo4jConnection.get_instance()
        second = Neo4jConnection.get_instance()

    assert first is second


def test_verify_connectivity_delegates_to_driver(valid_env) -> None:
    mock_driver = MagicMock()
    with patch.object(
        connection_module.GraphDatabase, "driver", return_value=mock_driver
    ):
        conn = Neo4jConnection()
        conn.verify_connectivity()

    mock_driver.verify_connectivity.assert_called_once()


def test_close_then_use_raises_runtime_error(valid_env) -> None:
    mock_driver = MagicMock()
    with patch.object(
        connection_module.GraphDatabase, "driver", return_value=mock_driver
    ):
        conn = Neo4jConnection()
        conn.close()

        with pytest.raises(RuntimeError):
            conn.verify_connectivity()
        with pytest.raises(RuntimeError):
            conn.session()
        with pytest.raises(RuntimeError):
            conn.get_driver()


def test_double_close_raises(valid_env) -> None:
    mock_driver = MagicMock()
    with patch.object(
        connection_module.GraphDatabase, "driver", return_value=mock_driver
    ):
        conn = Neo4jConnection()
        conn.close()
        with pytest.raises(RuntimeError):
            conn.close()


def test_session_dependency_yields_and_closes(valid_env) -> None:
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    with patch.object(
        connection_module.GraphDatabase, "driver", return_value=mock_driver
    ):
        conn = Neo4jConnection()
        gen = conn.get_session_dependency()
        yielded = next(gen)
        assert yielded is mock_session
        # Exhausting the generator triggers the finally-block close.
        with pytest.raises(StopIteration):
            next(gen)

    mock_session.close.assert_called_once()
