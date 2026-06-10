"""Tests for the RAG service module.

This module contains unit tests for the Retrieval-Augmented Generation service.
"""

from unittest.mock import MagicMock, patch

from src.services.rag import RAGService


class TestRAGService:
    """Test suite for the RAGService class."""

    @patch("src.services.llm.requests.post")
    @patch("src.services.embeddings.requests.post")
    def test_answer_question_success(
        self, mock_embed_post: MagicMock, mock_llm_post: MagicMock
    ) -> None:
        """Test successful question answering with context retrieval."""
        # Mock the embedding API response
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_embed_post.return_value = mock_embed_response

        # Mock the LLM API response
        mock_llm_response = MagicMock()
        mock_llm_response.json.return_value = {
            "response": "Emergency management involves coordinating response efforts."
        }
        mock_llm_post.return_value = mock_llm_response

        mock_session = MagicMock()

        def create_mock_record(text_value):
            record = MagicMock()
            record.__getitem__.side_effect = (
                lambda key: text_value if key == "text" else None
            )
            return record

        mock_session.run.return_value = [
            create_mock_record("Emergency management is the process...")
        ]

        # Execute
        rag_service = RAGService()
        result = rag_service.answer_question(
            "What is emergency management?", mock_session
        )

        # Assert
        assert result == "Emergency management involves coordinating response efforts."
        mock_session.run.assert_called_once()
        mock_embed_post.assert_called_once()
        mock_llm_post.assert_called_once()

    @patch("src.services.embeddings.requests.post")
    def test_answer_question_embedding_error(self, mock_embed_post: MagicMock) -> None:
        """Test handling of embedding generation errors."""
        mock_embed_post.side_effect = Exception("Embedding service unavailable")
        mock_session = MagicMock()

        rag_service = RAGService()
        result = rag_service.answer_question("test question", mock_session)

        assert "Error generating embeddings" in result

    @patch("src.services.embeddings.requests.post")
    def test_answer_question_no_results(self, mock_embed_post: MagicMock) -> None:
        """Test handling when no relevant documents are found."""
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1, 0.2]}
        mock_embed_post.return_value = mock_embed_response

        mock_session = MagicMock()
        mock_session.run.return_value = []

        rag_service = RAGService()
        result = rag_service.answer_question("obscure question", mock_session)

        assert "couldn't find any relevant information" in result

    @patch("src.services.llm.requests.post")
    @patch("src.services.embeddings.requests.post")
    def test_answer_question_response_error(
        self, mock_embed_post: MagicMock, mock_llm_post: MagicMock
    ) -> None:
        """Test handling of LLM response generation errors."""
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1, 0.2]}
        mock_embed_post.return_value = mock_embed_response

        mock_llm_post.side_effect = Exception("LLM service unavailable")

        mock_session = MagicMock()

        def create_mock_record(text_value):
            record = MagicMock()
            record.__getitem__.side_effect = (
                lambda key: text_value if key == "text" else None
            )
            return record

        mock_session.run.return_value = [create_mock_record("Some context")]

        rag_service = RAGService()
        result = rag_service.answer_question("test question", mock_session)

        assert "Error generating response" in result

    @patch("src.services.llm.requests.post")
    @patch("src.services.embeddings.requests.post")
    def test_answer_question_multiple_results(
        self, mock_embed_post: MagicMock, mock_llm_post: MagicMock
    ) -> None:
        """Test handling multiple retrieved documents."""
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1, 0.2]}
        mock_embed_post.return_value = mock_embed_response

        mock_llm_response = MagicMock()
        mock_llm_response.json.return_value = {"response": "Synthesized answer"}
        mock_llm_post.return_value = mock_llm_response

        mock_session = MagicMock()

        def create_mock_record(text_value):
            record = MagicMock()
            record.__getitem__.side_effect = (
                lambda key: text_value if key == "text" else None
            )
            return record

        texts = ["Document 1 content", "Document 2 content", "Document 3 content"]
        mock_session.run.return_value = [create_mock_record(text) for text in texts]

        rag_service = RAGService()
        rag_service.answer_question("test", mock_session)

        # Verify context was properly joined
        call_args = mock_llm_post.call_args
        payload = call_args[1]["json"]
        prompt = payload["prompt"]
        assert "Document 1 content" in prompt
        assert "Document 2 content" in prompt
        assert "Document 3 content" in prompt

    @patch("src.services.llm.requests.post")
    @patch("src.services.embeddings.requests.post")
    def test_answer_question_cypher_query_structure(
        self, mock_embed_post: MagicMock, mock_llm_post: MagicMock
    ) -> None:
        """Test that the correct Cypher query is executed."""
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1, 0.2]}
        mock_embed_post.return_value = mock_embed_response

        mock_llm_response = MagicMock()
        mock_llm_response.json.return_value = {"response": "answer"}
        mock_llm_post.return_value = mock_llm_response

        mock_session = MagicMock()

        def create_mock_record(text_value):
            record = MagicMock()
            record.__getitem__.side_effect = (
                lambda key: text_value if key == "text" else None
            )
            return record

        mock_session.run.return_value = [create_mock_record("context")]

        rag_service = RAGService()
        rag_service.answer_question("test", mock_session)

        # Verify the Cypher query was called with the embedding parameter
        call_args = mock_session.run.call_args
        cypher_query = call_args[0][0]
        assert "db.index.vector.queryNodes" in cypher_query
        assert "chunk_vector_idx" in cypher_query
        assert call_args[1]["embedding"] == [0.1, 0.2]

    @patch("src.services.llm.requests.post")
    @patch("src.services.embeddings.requests.post")
    def test_answer_question_prompt_format(
        self, mock_embed_post: MagicMock, mock_llm_post: MagicMock
    ) -> None:
        """Test the format of the prompt sent to the LLM."""
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1]}
        mock_embed_post.return_value = mock_embed_response

        mock_llm_response = MagicMock()
        mock_llm_response.json.return_value = {"response": "answer"}
        mock_llm_post.return_value = mock_llm_response

        mock_session = MagicMock()

        def create_mock_record(text_value):
            record = MagicMock()
            record.__getitem__.side_effect = (
                lambda key: text_value if key == "text" else None
            )
            return record

        mock_session.run.return_value = [create_mock_record("context text")]

        rag_service = RAGService()
        question = "What is emergency management?"
        rag_service.answer_question(question, mock_session)

        # Verify prompt structure
        call_args = mock_llm_post.call_args
        payload = call_args[1]["json"]
        prompt = payload["prompt"]
        assert "Context:" in prompt
        assert "Question:" in prompt
        assert "Answer:" in prompt
        assert "context text" in prompt
        assert question in prompt
