"""Shared pytest fixtures for the EM_B_V2 test suite.

Unit tests mock every external service (Neo4j, Ollama) so they run anywhere.
Integration tests (marked ``integration``) talk to the live containers and are
excluded from the default run — see ``pyproject.toml``.
"""

import logging
import os

import pytest


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear the shared rate limiter's counters before each test.

    The limiter keeps per-IP request counts in memory for the process lifetime,
    so without a reset the chat-endpoint tests would accumulate hits across tests
    and eventually trip the limit. Each test starts from a clean slate.
    """
    from src.core.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def restore_logging_state():
    """Undo any logging configuration a test performs.

    ``configure_logging`` mutates process-global loggers (handlers, level,
    ``propagate``). Left in place, it would stop later tests' ``caplog`` from
    seeing ``em_b`` records and keep rotating-file handles open on Windows temp
    dirs. Snapshot before each test, restore and close strays after.
    """
    names = ("em_b", "uvicorn", "uvicorn.access")
    saved = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    yield
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        for handler in handlers:
            if handler not in logger.handlers:
                logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.fixture
def sample_embedding() -> list[float]:
    """A 768-dimensional embedding matching ``embeddinggemma`` output."""
    return [0.1] * 768


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
