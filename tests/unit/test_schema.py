"""Unit tests for Cypher query validation helper."""

import pytest

from src.database.connection import validate_cypher_query

pytestmark = pytest.mark.unit


def test_parameterized_query_is_valid() -> None:
    assert validate_cypher_query("MATCH (n) WHERE n.id = $id RETURN n") is True


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n) WHERE n.id = {user_id}",  # f-string placeholder
        'MATCH (n) WHERE n.id = "x".format(y)',  # .format(
        "MATCH (n) WHERE n.id = 'a' + 'b'",  # string concatenation
    ],
)
def test_suspicious_queries_raise(query: str) -> None:
    with pytest.raises(ValueError):
        validate_cypher_query(query)


def test_vector_index_matches_embedding_dimensions() -> None:
    # A chunk embedding of any other size is silently left out of the index.
    from src.database import schema

    assert f"`vector.dimensions`: {schema.EMBEDDING_DIMENSIONS}," in (
        schema.INDEX_VECTOR_CHUNK
    )


def test_vector_queries_use_search_clause_pinned_to_cypher_25() -> None:
    # db.index.vector.queryNodes is deprecated in Neo4j 2026.08. SEARCH exists
    # only in Cypher 25, and the shipped Community server sets no default
    # language, so the version must be pinned in the query itself.
    from src.routers import graph
    from src.services import rag

    for query in (rag._VECTOR_QUERY, graph._VECTOR_SEARCH_QUERY):
        assert query.lstrip().startswith("CYPHER 25\n")
        assert "SEARCH node IN" in query
        assert "VECTOR INDEX chunk_vector_idx" in query
        assert "ORDER BY score DESC" in query


def test_no_code_calls_the_deprecated_vector_procedure() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = [
        str(path.relative_to(root))
        for folder in ("src", "pipeline")
        for path in (root / folder).rglob("*.py")
        if "db.index.vector.queryNodes(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
