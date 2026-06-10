"""FastAPI application entry point.

This module initializes the FastAPI application with Neo4j database integration
using the lifespan context manager for proper startup and shutdown handling.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI  # type: ignore[import-untyped]
from fastapi.staticfiles import StaticFiles  # type: ignore[import-untyped]

from src.database.connection import Neo4jConnection
from src.database.schema import setup_constraints
from src.routers import admin, chat, graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan event handler for startup and shutdown.

    This context manager handles:
    - Startup: Initialize Neo4j connection, validate it, and ingest data
    - Shutdown: Close Neo4j driver and cleanup resources

    Args:
        app: The FastAPI application instance.

    Yields:
        None (used by FastAPI to manage the app lifecycle).

    Raises:
        ValueError: If required environment variables are missing.
        Exception: If Neo4j connection or data ingestion fails during startup.
    """
    # Startup
    try:
        connection = Neo4jConnection.get_instance()
        connection.verify_connectivity()
        print("✓ Neo4j connection initialized successfully")

        setup_constraints(connection.get_driver())
        print("✓ Database schema constraints and indexes initialized")
    except ValueError as e:
        print(f"✗ Failed to initialize Neo4j connection: {e}")
        raise
    except Exception as e:
        print(f"✗ Unexpected error during Neo4j connection: {e}")
        raise

    yield

    # Shutdown
    try:
        connection.close()
        print("✓ Neo4j connection closed successfully")
    except RuntimeError as e:
        print(f"⚠ Warning during Neo4j shutdown: {e}")
    except Exception as e:
        print(f"✗ Unexpected error during Neo4j shutdown: {e}")


app = FastAPI(
    title="EM_B_V1 Knowledge Graph Chatbot",
    description="A chatbot that answers questions based on a knowledge graph",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(graph.router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        A dict indicating the API is healthy.
    """
    return {"status": "healthy"}


# Serve the chat UI — must be mounted last so API routes take priority
app.mount("/", StaticFiles(directory="src/static", html=True), name="static")
