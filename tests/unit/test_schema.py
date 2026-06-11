"""Unit tests for Cypher query validation helper."""

import pytest

from src.database.connection import validate_cypher_query

pytestmark = pytest.mark.unit


def test_parameterized_query_is_valid() -> None:
    assert validate_cypher_query("MATCH (n) WHERE n.id = $id RETURN n") is True


@pytest.mark.parametrize(
    "query",
    [
        'MATCH (n) WHERE n.id = {user_id}',  # f-string placeholder
        'MATCH (n) WHERE n.id = "x".format(y)',  # .format(
        "MATCH (n) WHERE n.id = 'a' + 'b'",  # string concatenation
    ],
)
def test_suspicious_queries_raise(query: str) -> None:
    with pytest.raises(ValueError):
        validate_cypher_query(query)
