"""Tests for the chat router module.

This module contains unit tests for chat endpoint request/response models and the chat route.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.routers.chat import ChatRequest, ChatResponse


class TestChatRequest:
    """Test suite for ChatRequest Pydantic model."""

    def test_chat_request_valid(self) -> None:
        """Test ChatRequest creation with valid data."""
        request = ChatRequest(question="What is emergency management?")
        assert request.question == "What is emergency management?"

    def test_chat_request_empty_question(self) -> None:
        """Test ChatRequest with empty question string."""
        request = ChatRequest(question="")
        assert request.question == ""

    def test_chat_request_missing_question(self) -> None:
        """Test ChatRequest validation when question is missing.

        Raises:
            ValidationError: When required field is missing.
        """
        with pytest.raises(ValidationError):
            ChatRequest.model_validate({})

    def test_chat_request_non_string_question(self) -> None:
        """Test ChatRequest validation with non-string question.

        Raises:
            ValidationError: When question is not a string.
        """
        with pytest.raises(ValidationError):
            ChatRequest.model_validate({"question": 123})

    def test_chat_request_with_special_characters(self) -> None:
        """Test ChatRequest with special characters in question."""
        special_question = "What is 2+2? & <emergency> management!"
        request = ChatRequest(question=special_question)
        assert request.question == special_question


class TestChatResponse:
    """Test suite for ChatResponse Pydantic model."""

    def test_chat_response_valid(self) -> None:
        """Test ChatResponse creation with valid data."""
        response = ChatResponse(answer="Emergency management is...")
        assert response.answer == "Emergency management is..."

    def test_chat_response_empty_answer(self) -> None:
        """Test ChatResponse with empty answer string."""
        response = ChatResponse(answer="")
        assert response.answer == ""

    def test_chat_response_missing_answer(self) -> None:
        """Test ChatResponse validation when answer is missing.

        Raises:
            ValidationError: When required field is missing.
        """
        with pytest.raises(ValidationError):
            ChatResponse.model_validate({})

    def test_chat_response_non_string_answer(self) -> None:
        """Test ChatResponse validation with non-string answer.

        Raises:
            ValidationError: When answer is not a string.
        """
        with pytest.raises(ValidationError):
            ChatResponse.model_validate({"answer": 456})

    def test_chat_response_long_answer(self) -> None:
        """Test ChatResponse with very long answer text."""
        long_answer = "This is a detailed answer. " * 1000
        response = ChatResponse(answer=long_answer)
        assert len(response.answer) > 0


class TestChatEndpoint:
    """Test suite for the chat endpoint."""

    def _setup_mocks(self):
        """Helper to setup session and connection mocks.

        Returns:
            A tuple of (mock_session, mock_connection).
        """
        mock_session = MagicMock()
        
        def session_generator():
            """Generator that yields a mocked session."""
            yield mock_session
        
        connection = MagicMock()
        connection.get_session_dependency = session_generator
        return mock_session, connection

    @patch("src.routers.chat.rag_service.answer_question")
    @patch("src.routers.chat.Neo4jConnection.get_instance")
    def test_chat_endpoint_success(
        self,
        mock_get_instance: MagicMock,
        mock_answer: MagicMock,
    ) -> None:
        """Test successful chat endpoint call.

        Args:
            mock_answer: Mocked RAGService.answer_question method.
            mock_get_instance: Mocked Neo4jConnection.get_instance.
        """
        mock_session, mock_connection = self._setup_mocks()
        mock_get_instance.return_value = mock_connection
        mock_answer.return_value = "Detailed answer to the question."

        from src.main import app

        client = TestClient(app)

        response = client.post(
            "/chat/",
            json={"question": "What is emergency management?"},
        )

        assert response.status_code == 200
        assert response.json()["answer"] == "Detailed answer to the question."

    @patch("src.routers.chat.Neo4jConnection.get_instance")
    def test_chat_endpoint_invalid_request(
        self,
        mock_get_instance: MagicMock,
    ) -> None:
        """Test chat endpoint with invalid request data.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance.
        """
        mock_session, mock_connection = self._setup_mocks()
        mock_get_instance.return_value = mock_connection

        from src.main import app

        client = TestClient(app)

        response = client.post(
            "/chat/",
            json={"invalid_field": "value"},
        )

        assert response.status_code == 422

    @patch("src.routers.chat.rag_service.answer_question")
    def test_chat_endpoint_error_handling(
        self,
        mock_answer: MagicMock,
    ) -> None:
        """Test chat endpoint error handling.

        Args:
            mock_answer: Mocked RAGService.answer_question method.
        """
        from src.main import app

        mock_answer.side_effect = Exception("Test error")

        client = TestClient(app)

        response = client.post(
            "/chat/",
            json={"question": "test"},
        )

        assert response.status_code == 500
        assert "Failed to process chat request" in response.json()["detail"]

    @patch("src.routers.chat.rag_service.answer_question")
    @patch("src.routers.chat.Neo4jConnection.get_instance")
    def test_chat_endpoint_empty_question(
        self,
        mock_get_instance: MagicMock,
        mock_answer: MagicMock,
    ) -> None:
        """Test chat endpoint with empty question.

        Args:
            mock_answer: Mocked RAGService.answer_question method.
            mock_get_instance: Mocked Neo4jConnection.get_instance.
        """
        mock_session, mock_connection = self._setup_mocks()

        from src.main import app

        mock_get_instance.return_value = mock_connection
        mock_answer.return_value = "Unable to process empty question"

        client = TestClient(app)

        response = client.post(
            "/chat/",
            json={"question": ""},
        )

        assert response.status_code == 200

    @patch("src.routers.chat.Neo4jConnection.get_instance")
    def test_chat_endpoint_response_model(
        self,
        mock_get_instance: MagicMock,
    ) -> None:
        """Test that chat endpoint returns ChatResponse model.

        Args:
            mock_get_instance: Mocked Neo4jConnection.get_instance.
        """
        mock_session, mock_connection = self._setup_mocks()

        from src.main import app

        mock_get_instance.return_value = mock_connection

        client = TestClient(app)

        response = client.post(
            "/chat/",
            json={"question": "test"},
        )

        # Verify response has the expected structure
        assert "answer" in response.json()
        assert isinstance(response.json()["answer"], str)
