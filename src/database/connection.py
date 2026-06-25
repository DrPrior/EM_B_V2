"""Neo4j connection manager module.

This module provides a singleton connection manager for Neo4j database access.
It uses context managers and dependency injection for safe resource management,
and validates Cypher queries to prevent injection vulnerabilities.
"""

import os
import threading
from collections.abc import Generator

from neo4j import (  # type: ignore[import-untyped]
    WRITE_ACCESS,
    Driver,
    GraphDatabase,
    Session,
)


class Neo4jConnection:
    """Singleton connection manager for Neo4j database.

    This class manages the lifecycle of a Neo4j driver instance using the singleton
    pattern. It provides context manager support for safe session management and
    a dependency injection method for FastAPI route handlers.

    Attributes:
        _instance: Class-level singleton instance.
        _lock: Thread-safe lock for singleton initialization.
        _driver: Neo4j driver instance (private), or None after close() is called.
        _uri: Database connection URI (private).

    Raises:
        ValueError: If required environment variables (NEO4J_AUTH, DB_URI) are missing.
        ServiceUnavailable: If the Neo4j database cannot be reached during operations.
    """

    _instance: "Neo4jConnection | None" = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the Neo4j connection manager.

        Reads NEO4J_AUTH and DB_URI from environment variables and creates
        a Neo4j driver instance. The driver is lazy-initialized and reused
        for all connections.

        Raises:
            ValueError: If NEO4J_AUTH or DB_URI environment variables are missing.
        """
        auth = os.environ.get("NEO4J_AUTH")
        uri = os.environ.get("DB_URI")
        if not auth:
            raise ValueError(
                "NEO4J_AUTH environment variable is not set. "
                "Format: 'username/password'"
            )
        if not uri:
            raise ValueError(
                "DB_URI environment variable is not set. Format: 'bolt://hostname:7687'"
            )

        # Parse auth string: "username/password"
        try:
            username, password = auth.split("/", 1)
        except ValueError as e:
            raise ValueError(
                "NEO4J_AUTH format is invalid. Expected 'username/password'. "
                f"Got: '{auth}'"
            ) from e

        self._uri: str = uri
        self._driver: Driver | None = GraphDatabase.driver(
            uri, auth=(username, password)
        )

    @classmethod
    def get_instance(cls) -> "Neo4jConnection":
        """Get or create the singleton instance.

        This method is thread-safe and ensures only one instance of
        Neo4jConnection is created, even with concurrent calls.

        Returns:
            The singleton Neo4jConnection instance.

        Raises:
            ValueError: If required environment variables are missing.
        """
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def verify_connectivity(self) -> None:
        """Verify that the database connection is active and valid.

        Raises:
            Exception: If the connection cannot be established.
            RuntimeError: If the driver has been closed.
        """
        if self._driver is None:
            raise RuntimeError(
                "Driver is not initialized or has been closed. "
                "Cannot verify connectivity."
            )
        self._driver.verify_connectivity()

    def session(self, access_mode: str = WRITE_ACCESS) -> Session:
        """Create and return a new Neo4j session.

        Use this method as a context manager for non-FastAPI database operations:
        `with connection.session() as session:`

        Args:
            access_mode: Transaction access mode for the session. Defaults to
                WRITE_ACCESS. Pass READ_ACCESS for read-only sessions; the server
                rejects any write attempted within a READ transaction.

        Returns:
            A Neo4j session object for database operations.

        Raises:
            RuntimeError: If the driver has been closed.
        """
        if self._driver is None:
            raise RuntimeError(
                "Driver is not initialized or has been closed. Cannot create a session."
            )
        return self._driver.session(default_access_mode=access_mode)

    def get_driver(self) -> Driver:
        """Get the Neo4j driver instance.

        Returns:
            The Neo4j driver instance.

        Raises:
            RuntimeError: If the driver has been closed.
        """
        if self._driver is None:
            raise RuntimeError(
                "Driver is not initialized or has been closed. Cannot retrieve driver."
            )
        return self._driver

    def close(self) -> None:
        """Close the Neo4j driver and cleanup resources.

        This should be called during FastAPI shutdown to ensure all
        connections are properly released.

        Raises:
            RuntimeError: If the driver is already closed.
        """
        if self._driver is not None:
            self._driver.close()
            self._driver = None
        else:
            raise RuntimeError("Driver is already closed or was never initialized.")

    def get_session_dependency(
        self, access_mode: str = WRITE_ACCESS
    ) -> Generator[Session, None, None]:
        """FastAPI dependency generator for Neo4j session injection.

        This method yields a Neo4j session for use in FastAPI route handlers.
        The session is automatically closed when the dependency is cleaned up
        (after the route completes).

        Usage:
            @app.get("/nodes")
            def get_nodes(
                session: Session = Depends(
                    Neo4jConnection.get_instance().get_session_dependency
                )
            ):
                # Use session for database operations
                pass

        Args:
            access_mode: Transaction access mode for the session. Defaults to
                WRITE_ACCESS. Read-only routes (chat, graph) should pass
                READ_ACCESS so the server rejects any accidental write.

        Yields:
            A Neo4j session for database operations.

        Raises:
            ServiceUnavailable: If the driver cannot create a session.
            RuntimeError: If the driver has been closed.
        """
        if self._driver is None:
            raise RuntimeError(
                "Driver is not initialized or has been closed. Cannot create a session."
            )
        session = self._driver.session(default_access_mode=access_mode)
        try:
            yield session
        finally:
            session.close()


def validate_cypher_query(query: str) -> bool:
    """Validate that a Cypher query uses parameterized placeholders.

    This function checks that a Cypher query uses parameterized syntax
    (e.g., $param_name) instead of f-strings or string concatenation.
    Parameterization is critical for preventing Cypher injection attacks.

    Args:
        query: The Cypher query string to validate.

    Returns:
        True if the query appears safe (uses parameterization).

    Raises:
        ValueError: If the query contains suspicious patterns indicating
            unsafe string interpolation (f-strings or format calls).

    Example:
        # Valid - uses parameterization:
        validate_cypher_query("MATCH (n) WHERE n.id = $id")  # OK

        # Invalid - uses f-string:
        validate_cypher_query(f"MATCH (n) WHERE n.id = {user_id}")  # Raises ValueError

    Note:
        This is a simple heuristic check. It catches common injection patterns
        but is not a complete validation. Developer responsibility to use
        parameterized queries throughout the codebase.
    """
    # Check for common f-string or format patterns that indicate unsafe queries
    suspicious_patterns = [
        "{",  # f-string or .format() placeholder
        ".format(",  # .format() method
        "% ",  # % string formatting
        "+",  # String concatenation (often a sign of injection)
    ]

    for pattern in suspicious_patterns:
        if pattern in query:
            raise ValueError(
                f"Query contains suspicious pattern '{pattern}' which suggests "
                "unsafe string interpolation. Use parameterized queries with "
                "placeholders like $param_name: "
                f"'{query}'"
            )

    return True
