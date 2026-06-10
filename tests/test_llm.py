"""Tests for the LLM service module.

This module contains unit tests for LLM response generation via Ollama API.
"""

import pytest
from unittest.mock import patch, MagicMock
from src.services.llm import generate_response


class TestGenerateResponse:
    """Test suite for the generate_response function."""

    @patch("src.services.llm.requests.post")
    def test_generate_response_success(self, mock_post: MagicMock) -> None:
        """Test successful response generation from LLM.

        Args:
            mock_post: Mocked requests.post function.
        """
        expected_response = "This is a test response from the LLM."
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": expected_response}
        mock_post.return_value = mock_response

        result = generate_response("What is emergency management?")

        assert result == expected_response
        mock_post.assert_called_once()

    @patch("src.services.llm.requests.post")
    def test_generate_response_empty_response(self, mock_post: MagicMock) -> None:
        """Test handling of empty response from LLM.

        Args:
            mock_post: Mocked requests.post function.
        """
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        result = generate_response("test prompt")

        assert result == ""

    @patch("src.services.llm.requests.post")
    def test_generate_response_api_error(self, mock_post: MagicMock) -> None:
        """Test handling of API errors during response generation.

        Args:
            mock_post: Mocked requests.post function.

        Raises:
            HTTPError: When the API request fails.
        """
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("Connection Error")
        mock_post.return_value = mock_response

        with pytest.raises(Exception, match="Connection Error"):
            generate_response("test prompt")

    @patch("src.services.llm.requests.post")
    @patch("src.services.llm.settings")
    def test_generate_response_uses_correct_url(
        self, mock_settings: MagicMock, mock_post: MagicMock
    ) -> None:
        """Test that the correct Ollama API URL is used.

        Args:
            mock_settings: Mocked settings object.
            mock_post: Mocked requests.post function.
        """
        mock_settings.OLLAMA_BASE_URL = "http://ollama:11434"
        mock_settings.CHAT_MODEL = "gemma:latest"
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Test"}
        mock_post.return_value = mock_response

        generate_response("test prompt")

        expected_url = "http://ollama:11434/api/generate"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == expected_url

    @patch("src.services.llm.requests.post")
    @patch("src.services.llm.settings")
    def test_generate_response_payload_structure(
        self, mock_settings: MagicMock, mock_post: MagicMock
    ) -> None:
        """Test that the request payload has the correct structure.

        Args:
            mock_settings: Mocked settings object.
            mock_post: Mocked requests.post function.
        """
        mock_settings.OLLAMA_BASE_URL = "http://localhost:11434"
        mock_settings.CHAT_MODEL = "gemma:latest"
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Test"}
        mock_post.return_value = mock_response

        generate_response("test prompt")

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        assert "model" in payload
        assert "prompt" in payload
        assert "stream" in payload
        assert "options" in payload
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.3

    @patch("src.services.llm.requests.post")
    def test_generate_response_with_long_prompt(
        self, mock_post: MagicMock
    ) -> None:
        """Test response generation with lengthy prompts.

        Args:
            mock_post: Mocked requests.post function.
        """
        long_prompt = "This is a very long prompt. " * 100
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Comprehensive answer"}
        mock_post.return_value = mock_response

        result = generate_response(long_prompt)

        assert result == "Comprehensive answer"
        mock_post.assert_called_once()

    @patch("src.services.llm.requests.post")
    def test_generate_response_with_special_characters(
        self, mock_post: MagicMock
    ) -> None:
        """Test response generation with special characters in prompt.

        Args:
            mock_post: Mocked requests.post function.
        """
        prompt_with_special_chars = "What is 2+2? & <tag> special chars!"
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "2+2=4"}
        mock_post.return_value = mock_response

        result = generate_response(prompt_with_special_chars)

        assert result == "2+2=4"
