"""Shared pytest fixtures for the EM_B_V2 test suite.

Unit tests mock every external service (Neo4j, Ollama) so they run anywhere.
Integration tests (marked ``integration``) talk to the live containers and are
excluded from the default run — see ``pyproject.toml``.
"""

import os

import pytest


@pytest.fixture
def sample_embedding() -> list[float]:
    """A 2560-dimensional embedding matching ``qwen3-embedding:4b`` output."""
    return [0.1] * 2560


@pytest.fixture
def fake_record():
    """Factory for objects that behave like Neo4j records (``record["key"]``).

    Neo4j ``Record`` objects support ``__getitem__`` by key, which a plain dict
    already satisfies. This factory just makes intent explicit in tests.
    """

    def _make(**fields):
        return dict(fields)

    return _make


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL of the live API as seen from inside the api container."""
    return os.environ.get("TEST_API_BASE_URL", "http://localhost:8000")
