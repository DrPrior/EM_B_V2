"""Graph query router for Neo4j endpoints.

This module provides REST API endpoints for querying and searching
the Neo4j knowledge graph.
"""

from typing import Generator

from fastapi import APIRouter, Depends, HTTPException, status
from neo4j import ManagedTransaction, Record, Session
from pydantic import BaseModel, Field

from src.database.connection import Neo4jConnection
from src.models import NodeResponse, SearchResponse
from src.services.embeddings import generate_embedding

router = APIRouter(prefix="/graph", tags=["graph"])


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency for session injection.

    Yields a Neo4j session for each request and ensures cleanup after completion.

    Yields:
        A Neo4j session for database operations.

    Raises:
        RuntimeError: If the Neo4j driver has been closed or is unavailable.
    """
    yield from Neo4jConnection.get_instance().get_session_dependency()


@router.get("/nodes", response_model=list[NodeResponse])
def get_nodes(session: Session = Depends(get_session)) -> list[NodeResponse]:
    """Get all nodes from the graph (with limit).

    Retrieves up to 10 nodes from the Neo4j database. Useful for exploring
    the graph structure and understanding available data.

    Args:
        session: Neo4j session injected via dependency injection.

    Returns:
        List of NodeResponse objects containing node data.

    Raises:
        HTTPException: 500 if the query fails, 503 if database is unavailable.

    Example:
        GET /graph/nodes
        Response: [
            {
                "element_id": "4:abc123",
                "labels": ["Person"],
                "properties": {"name": "Alice", "age": 30}
            },
            ...
        ]
    """
    try:
        result = session.execute_read(
            _query_nodes
        )
        nodes = [
            NodeResponse(
                element_id=str(record["id"]),
                labels=list(record["labels"]),
                properties=dict(record["props"]),
            )
            for record in result
        ]
        return nodes
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve nodes: {str(e)}",
        )


def _query_nodes(tx: ManagedTransaction) -> list[Record]:
    """Execute query to retrieve nodes.

    Args:
        tx: Neo4j transaction object.

    Returns:
        List of records with node data.
    """
    result = tx.run(
        "MATCH (n) RETURN elementId(n) as id, labels(n) as labels, properties(n) as props LIMIT 10"
    )
    return list(result)


@router.get("/nodes/{node_id}", response_model=NodeResponse)
def get_node_by_id(node_id: str, session: Session = Depends(get_session)) -> NodeResponse:
    """Get a specific node by its element ID.

    Retrieves a single node from the graph by its unique Neo4j element ID.

    Args:
        node_id: The element ID of the node to retrieve.
        session: Neo4j session injected via dependency injection.

    Returns:
        NodeResponse object with the node's data.

    Raises:
        HTTPException: 404 if node not found, 500 if query fails, 503 if database unavailable.

    Example:
        GET /graph/nodes/4:abc123
        Response: {
            "element_id": "4:abc123",
            "labels": ["Person"],
            "properties": {"name": "Alice", "age": 30}
        }
    """
    try:
        result = session.execute_read(
            _query_node_by_id, node_id=node_id
        )
        record = result
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Node with ID {node_id} not found",
            )
        return NodeResponse(
            element_id=str(record["id"]),
            labels=list(record["labels"]),
            properties=dict(record["props"]),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve node: {str(e)}",
        )


def _query_node_by_id(tx: ManagedTransaction, node_id: str) -> Record | None:
    """Execute query to retrieve a specific node.

    Args:
        tx: Neo4j transaction object.
        node_id: The element ID of the node to retrieve.

    Returns:
        Single record with node data, or None if not found.
    """
    result = tx.run(
        "MATCH (n) WHERE elementId(n) = $id RETURN elementId(n) as id, labels(n) as labels, properties(n) as props LIMIT 1",
        id=node_id
    )
    records = list(result)
    return records[0] if records else None


@router.get("/search", response_model=SearchResponse)
def search_nodes(q: str, session: Session = Depends(get_session)) -> SearchResponse:
    """Search for nodes by property values.

    Searches the graph for nodes whose properties contain the search term.
    Useful for finding specific entities by name or other identifying properties.

    Args:
        q: Search term to find in node properties (required, non-empty).
        session: Neo4j session injected via dependency injection.

    Returns:
        SearchResponse object containing matching nodes and result count.

    Raises:
        HTTPException: 400 if search term is empty, 500 if query fails, 503 if database unavailable.

    Example:
        GET /graph/search?q=Alice
        Response: {
            "query": "Alice",
            "total_results": 1,
            "results": [
                {
                    "element_id": "4:abc123",
                    "labels": ["Person"],
                    "properties": {"name": "Alice", "age": 30}
                }
            ]
        }
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query (q parameter) cannot be empty",
        )

    try:
        results = session.execute_read(
            _query_search, search_term=q.strip()
        )
        nodes = [
            NodeResponse(
                element_id=str(record["id"]),
                labels=list(record["labels"]),
                properties=dict(record["props"]),
            )
            for record in results
        ]
        return SearchResponse(
            query=q,
            total_results=len(nodes),
            results=nodes,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}",
        )


def _query_search(tx: ManagedTransaction, search_term: str) -> list[Record]:
    """Execute search query across node properties.

    Args:
        tx: Neo4j transaction object.
        search_term: The term to search for in node properties.

    Returns:
        List of records with matching nodes.
    """
    result = tx.run(
        "MATCH (n) WHERE ANY(prop IN properties(n) | toString(prop) CONTAINS $search) RETURN elementId(n) as id, labels(n) as labels, properties(n) as props LIMIT 20",
        search=search_term
    )
    return list(result)


class VectorSearchRequest(BaseModel):
    """Request model for vector similarity search."""

    query: str = Field(..., description="The search query text to embed and search.")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of top results to return.")


@router.post("/search", response_model=SearchResponse)
def vector_search(
    request: VectorSearchRequest, session: Session = Depends(get_session)
) -> SearchResponse:
    """Perform a vector similarity search across chunk embeddings.

    Embeds the incoming text query using the embedding service, then searches
    the Neo4j vector index (`chunk_vector_idx`) for semantically similar nodes.

    Args:
        request: The vector search request containing query and limit parameters.
        session: Neo4j session injected via dependency injection.

    Returns:
        SearchResponse object containing matching nodes and result count.

    Raises:
        HTTPException: 500 if embedding generation or database query fails.
    """
    try:
        query_vector = generate_embedding(request.query)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate embedding: {str(e)}",
        )

    try:
        results = session.execute_read(
            _query_vector_search, embedding=query_vector, top_k=request.top_k
        )
        nodes = [
            NodeResponse(
                element_id=str(record["id"]),
                labels=list(record["labels"]),
                properties=dict(record["props"]),
            )
            for record in results
        ]
        return SearchResponse(
            query=request.query,
            total_results=len(nodes),
            results=nodes,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {str(e)}",
        )


def _query_vector_search(
    tx: ManagedTransaction, embedding: list[float], top_k: int
) -> list[Record]:
    """Execute vector similarity search query.

    Args:
        tx: Neo4j transaction object.
        embedding: The vector embedding of the search query.
        top_k: Maximum number of results to return.

    Returns:
        List of records with matching nodes and their similarity scores.
    """
    query = """
    CALL db.index.vector.queryNodes('chunk_vector_idx', $top_k, $embedding)
    YIELD node, score
    RETURN elementId(node) as id, labels(node) as labels, properties(node) as props, score
    """
    result = tx.run(query, embedding=embedding, top_k=top_k)
    return list(result)
