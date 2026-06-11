"""Unit tests for Pydantic API response models."""

import pytest
from pydantic import ValidationError

from src.models import NodeResponse, RelationshipResponse, SearchResponse

pytestmark = pytest.mark.unit


def test_node_response_defaults() -> None:
    node = NodeResponse(element_id="4:abc")

    assert node.element_id == "4:abc"
    assert node.labels == []
    assert node.properties == {}


def test_node_response_full() -> None:
    node = NodeResponse(
        element_id="4:abc", labels=["Concept"], properties={"name": "ICS"}
    )

    assert node.labels == ["Concept"]
    assert node.properties == {"name": "ICS"}


def test_node_response_requires_element_id() -> None:
    with pytest.raises(ValidationError):
        NodeResponse(labels=["Concept"])


def test_relationship_response_requires_core_fields() -> None:
    rel = RelationshipResponse(
        element_id="5:def",
        type_name="MENTIONS",
        start_node_id="4:a",
        end_node_id="4:b",
    )

    assert rel.type_name == "MENTIONS"
    assert rel.properties == {}


def test_relationship_response_missing_field_raises() -> None:
    with pytest.raises(ValidationError):
        RelationshipResponse(element_id="5:def", type_name="MENTIONS")


def test_search_response_serializes_nested_nodes() -> None:
    response = SearchResponse(
        query="ICS",
        total_results=1,
        results=[NodeResponse(element_id="4:abc", labels=["Concept"])],
    )

    dumped = response.model_dump()
    assert dumped["query"] == "ICS"
    assert dumped["total_results"] == 1
    assert dumped["results"][0]["element_id"] == "4:abc"


def test_search_response_defaults_empty_results() -> None:
    response = SearchResponse(query="x", total_results=0)

    assert response.results == []
