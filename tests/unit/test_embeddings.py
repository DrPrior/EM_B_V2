"""Unit tests for the embeddings service (Ollama + Neo4j mocked)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services.embeddings import embed_and_store_chunk, generate_embedding

pytestmark = pytest.mark.unit


def test_generate_embedding_returns_vector() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    mock_response.raise_for_status.return_value = None

    with patch(
        "src.services.embeddings.requests.post", return_value=mock_response
    ) as p:
        result = generate_embedding("hello")

    assert result == [0.1, 0.2, 0.3]
    # Hits the Ollama embeddings endpoint with the configured model.
    _, kwargs = p.call_args
    assert kwargs["json"]["prompt"] == "hello"
    assert "model" in kwargs["json"]


def test_generate_embedding_missing_key_returns_empty() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status.return_value = None

    with patch("src.services.embeddings.requests.post", return_value=mock_response):
        assert generate_embedding("hi") == []


def test_generate_embedding_propagates_http_error() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("500")

    with patch("src.services.embeddings.requests.post", return_value=mock_response):
        with pytest.raises(requests.HTTPError):
            generate_embedding("hi")


def test_embed_and_store_chunk_writes_when_vector_present() -> None:
    session = MagicMock()

    with patch(
        "src.services.embeddings.generate_embedding", return_value=[0.1, 0.2]
    ):
        embed_and_store_chunk("text", "chunk-1", session)

    session.execute_write.assert_called_once()
    _, kwargs = session.execute_write.call_args
    assert kwargs["chunk_id"] == "chunk-1"
    assert kwargs["embedding"] == [0.1, 0.2]


def test_embed_and_store_chunk_skips_empty_vector() -> None:
    session = MagicMock()

    with patch("src.services.embeddings.generate_embedding", return_value=[]):
        embed_and_store_chunk("text", "chunk-1", session)

    session.execute_write.assert_not_called()
