"""Pydantic models for API responses.

This module defines the data models used for validating and serializing
API responses, particularly for Neo4j graph data.
"""

from pydantic import BaseModel, ConfigDict, Field


class NodeResponse(BaseModel):
    """Represents a Neo4j graph node in API responses.

    Attributes:
        element_id: Unique identifier for the node in Neo4j.
        labels: List of node labels (e.g., ['Person', 'User']).
        properties: Dictionary of node properties (key-value pairs).

    Example:
        {
            "element_id": "4:abc123",
            "labels": ["Person"],
            "properties": {"name": "Alice", "age": 30}
        }
    """

    element_id: str = Field(..., description="Unique Neo4j element ID")
    labels: list[str] = Field(default_factory=list, description="Node labels")
    properties: dict = Field(default_factory=dict, description="Node properties")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "element_id": "4:abc123",
                "labels": ["Person"],
                "properties": {"name": "Alice", "age": 30},
            }
        }
    )


class RelationshipResponse(BaseModel):
    """Represents a Neo4j graph relationship in API responses.

    Attributes:
        element_id: Unique identifier for the relationship in Neo4j.
        type_name: The relationship type (e.g., 'KNOWS', 'WORKS_FOR').
        start_node_id: Element ID of the start node.
        end_node_id: Element ID of the end node.
        properties: Dictionary of relationship properties.

    Example:
        {
            "element_id": "5:def456",
            "type_name": "KNOWS",
            "start_node_id": "4:abc123",
            "end_node_id": "4:xyz789",
            "properties": {"since": 2020}
        }
    """

    element_id: str = Field(..., description="Unique Neo4j element ID")
    type_name: str = Field(..., description="Relationship type")
    start_node_id: str = Field(..., description="Start node element ID")
    end_node_id: str = Field(..., description="End node element ID")
    properties: dict = Field(
        default_factory=dict, description="Relationship properties"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "element_id": "5:def456",
                "type_name": "KNOWS",
                "start_node_id": "4:abc123",
                "end_node_id": "4:xyz789",
                "properties": {"since": 2020},
            }
        }
    )


class SearchResponse(BaseModel):
    """Represents search results for graph queries.

    Attributes:
        query: The search query that was executed.
        total_results: Total number of results found.
        results: List of NodeResponse objects matching the query.
    """

    query: str = Field(..., description="Search query executed")
    total_results: int = Field(..., description="Total results found")
    results: list[NodeResponse] = Field(
        default_factory=list, description="Matching nodes"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Alice",
                "total_results": 1,
                "results": [
                    {
                        "element_id": "4:abc123",
                        "labels": ["Person"],
                        "properties": {"name": "Alice"},
                    }
                ],
            }
        }
    )
