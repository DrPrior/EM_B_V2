"""FastAPI application entry point.

This module initializes the FastAPI application with Neo4j database integration
using the lifespan context manager for proper startup and shutdown handling.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI  # type: ignore[import-untyped]
from fastapi.staticfiles import StaticFiles  # type: ignore[import-untyped]
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.core.logging_config import configure_logging
from src.core.paths import static_dir
from src.core.rate_limit import limiter
from src.database.connection import Neo4jConnection
from src.database.schema import setup_constraints
from src.routers import admin, chat, files, graph
from src.services.ollama_bootstrap import OllamaUnavailableError, bootstrap

logger = logging.getLogger("em_b.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan event handler for startup and shutdown.

    This context manager handles:
    - Startup: Initialize Neo4j connection, provision host-native Ollama models
    - Shutdown: Close Neo4j driver and cleanup resources

    Args:
        app: The FastAPI application instance.

    Yields:
        None (used by FastAPI to manage the app lifecycle).

    Raises:
        ValueError: If required environment variables are missing.
        OllamaUnavailableError: If the host Ollama daemon cannot be reached or
            the required models cannot be provisioned (fail-fast).
        Exception: If Neo4j connection or data ingestion fails during startup.
    """
    # Startup — logging first, so every later startup failure is recorded.
    log_dir = configure_logging()
    logger.info(
        "API starting; logging to %s",
        log_dir / "api.log" if log_dir else "console",
    )

    try:
        connection = Neo4jConnection.get_instance()
        connection.verify_connectivity()
        logger.info("Neo4j connection initialized")

        setup_constraints(connection.get_driver())
        logger.info("Database schema constraints and indexes initialized")
    except ValueError:
        logger.exception("Failed to initialize Neo4j connection")
        raise
    except Exception:
        logger.exception("Unexpected error during Neo4j connection")
        raise

    # Provision the host-native (hybrid) Ollama daemon: wait for it to be
    # reachable, then pull base models and build the custom variants if missing.
    # Fail fast — a running API with no usable Ollama only yields broken chat.
    try:
        bootstrap()
        logger.info("Host Ollama reachable and required models provisioned")
    except OllamaUnavailableError:
        logger.exception("Host Ollama unavailable; API cannot start")
        raise

    yield

    # Shutdown
    try:
        connection.close()
        logger.info("Neo4j connection closed")
    except RuntimeError as e:
        logger.warning("Warning during Neo4j shutdown: %s", e)
    except Exception:
        logger.exception("Unexpected error during Neo4j shutdown")


app = FastAPI(
    title="EM_B_V1 Knowledge Graph Chatbot",
    description="A chatbot that answers questions based on a knowledge graph",
    version="0.1.0",
    lifespan=lifespan,
)

# Per-IP rate limiting: register the shared limiter and the 429 handler so the
# @limiter.limit decorators on the chat endpoints take effect.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include routers
app.include_router(graph.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(files.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        A dict indicating the API is healthy.
    """
    return {"status": "healthy"}


# Serve the chat UI — must be mounted last so API routes take priority.
# Resolved via static_dir() so it works from source and inside a frozen bundle,
# independent of the current working directory.
app.mount("/", StaticFiles(directory=str(static_dir()), html=True), name="static")
