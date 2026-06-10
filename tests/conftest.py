"""Pytest configuration and shared fixtures.

This module provides shared test configuration and reusable fixtures for all test modules.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_neo4j_session() -> MagicMock:
    """Fixture providing a mocked Neo4j session.

    Returns:
        A mocked Neo4j session object with common methods.
    """
    session = MagicMock()
    # Don't set a default return value here - let individual tests set it
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_neo4j_connection() -> MagicMock:
    """Fixture providing a mocked Neo4j connection.

    Returns:
        A mocked Neo4j connection object with driver and session methods.
    """
    connection = MagicMock()
    connection.close = MagicMock()
    connection.get_session_dependency = MagicMock()
    return connection


@pytest.fixture
def sample_embedding_vector() -> list[float]:
    """Fixture providing a sample embedding vector.

    Returns:
        A sample 2560-dimensional embedding vector normalized to unit length.
    """
    return [0.1] * 2560


@pytest.fixture
def sample_question() -> str:
    """Fixture providing a sample question.

    Returns:
        A sample emergency management question.
    """
    return "What are the principles of emergency management?"


@pytest.fixture
def sample_context_documents() -> list[dict[str, str]]:
    """Fixture providing sample context documents retrieved from knowledge graph.

    Returns:
        A list of sample document records as would be returned from Neo4j.
    """
    return [
        {
            "text": "Emergency Management is the discipline and profession of applying "
            "science, technology, planning, and management to deal with extreme events "
            "that threaten society."
        },
        {
            "text": "The Incident Command System (ICS) is a standardized organizational "
            "structure for managing emergency response operations."
        },
        {
            "text": "Emergency preparedness involves planning, training, and equipping to "
            "effectively respond to emergencies."
        },
    ]


@pytest.fixture
def sample_response() -> str:
    """Fixture providing a sample LLM response.

    Returns:
        A sample response from the language model.
    """
    return (
        "Emergency management is a comprehensive approach to managing disasters and "
        "emergencies. The principles include: 1) Prevention and mitigation of risks, "
        "2) Preparedness through planning and training, 3) Response to emergencies, "
        "and 4) Recovery and restoration."
    )
