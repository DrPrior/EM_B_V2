"""Tests for the embeddings service module.

This module contains unit tests for embedding generation via Ollama API.
"""

import pytest
from unittest.mock import patch, MagicMock
from src.services.embeddings import generate_embedding


class TestGenerateEmbedding:
    """Test suite for the generate_embedding function."""

    @patch("src.services.embeddings.requests.post")
    def test_generate_embedding_success(self, mock_post: MagicMock) -> None:
        """Test successful embedding generation.

        Args:
            mock_post: Mocked requests.post function.
        """
        expected_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": expected_embedding}
        mock_post.return_value = mock_response

        result = generate_embedding("test query")

        assert result == expected_embedding
        mock_post.assert_called_once()

    @patch("src.services.embeddings.requests.post")
    def test_generate_embedding_empty_response(self, mock_post: MagicMock) -> None:
        """Test handling of empty embedding in response.

        Args:
            mock_post: Mocked requests.post function.
        """
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        result = generate_embedding("test query")

        assert result == []

    @patch("src.services.embeddings.requests.post")
    def test_generate_embedding_api_error(self, mock_post: MagicMock) -> None:
        """Test handling of API errors during embedding generation.

        Args:
            mock_post: Mocked requests.post function.

        Raises:
            HTTPError: When the API request fails.
        """
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_post.return_value = mock_response

        with pytest.raises(Exception, match="API Error"):
            generate_embedding("test query")

    @patch("src.services.embeddings.requests.post")
    @patch("src.services.embeddings.settings")
    def test_generate_embedding_uses_correct_url(
        self, mock_settings: MagicMock, mock_post: MagicMock
    ) -> None:
        """Test that the correct Ollama API URL is used.

        Args:
            mock_settings: Mocked settings object.
            mock_post: Mocked requests.post function.
        """
        mock_settings.OLLAMA_BASE_URL = "http://ollama:11434"
        mock_settings.EMBEDDING_MODEL = "nomic-embed-text"
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1, 0.2]}
        mock_post.return_value = mock_response

        generate_embedding("test")

        expected_url = "http://ollama:11434/api/embeddings"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == expected_url

    @patch("src.services.embeddings.requests.post")
    def test_generate_embedding_with_large_vector(
        self, mock_post: MagicMock
    ) -> None:
        """Test embedding generation with large vector dimensions.

        Args:
            mock_post: Mocked requests.post function.
        """
        large_embedding = [0.1] * 2560  # 2560-dimensional embedding
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": large_embedding}
        mock_post.return_value = mock_response

        result = generate_embedding("long text")

        assert len(result) == 2560
        assert result == large_embedding
