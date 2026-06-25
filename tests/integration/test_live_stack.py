"""Integration tests against the live Neo4j + Ollama + API stack.

These run inside the ``api`` container (where the app is reachable at
``localhost:8000`` and Neo4j/Ollama at their compose hostnames). They are
excluded from the default ``pytest`` run; invoke with ``pytest -m integration``.
"""

import pytest
import requests

from src.database.connection import Neo4jConnection
from src.services.embeddings import generate_embedding

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def api(base_url: str) -> str:
    """Skip the whole module if the live API is not reachable."""
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - infra guard
        pytest.skip(f"Live API not reachable at {base_url}: {exc}")
    return base_url


def test_health_live(api: str) -> None:
    resp = requests.get(f"{api}/health", timeout=5)

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_graph_nodes_live(api: str) -> None:
    resp = requests.get(f"{api}/graph/nodes", timeout=15)

    assert resp.status_code == 200
    nodes = resp.json()
    assert isinstance(nodes, list)
    if nodes:  # the imported v1 volume should contain data
        assert "element_id" in nodes[0]
        assert "labels" in nodes[0]


def test_text_search_live(api: str) -> None:
    resp = requests.get(f"{api}/graph/search", params={"q": "the"}, timeout=15)

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "the"
    assert "total_results" in body
    assert isinstance(body["results"], list)


def test_embedding_dimensions_live() -> None:
    vector = generate_embedding("emergency management principles")

    assert isinstance(vector, list)
    assert len(vector) == 2560  # qwen3-embedding:4b
    assert all(isinstance(x, float) for x in vector[:10])


def test_vector_search_live(api: str) -> None:
    resp = requests.post(
        f"{api}/graph/search",
        json={"query": "emergency management", "top_k": 3},
        timeout=60,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "emergency management"
    assert isinstance(body["results"], list)
    assert len(body["results"]) <= 3


def test_neo4j_direct_query_live() -> None:
    conn = Neo4jConnection()  # fresh instance; reads live env vars
    try:
        conn.verify_connectivity()
        with conn.session() as session:
            record = session.run("RETURN 1 AS n").single()
        assert record["n"] == 1
    finally:
        conn.close()


def test_chat_round_trip_live(api: str) -> None:
    resp = requests.post(
        f"{api}/chat/",
        json={"question": "What is emergency management?"},
        timeout=180,  # real LLM generation can be slow
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"].strip()
    assert body["session_id"]
    assert isinstance(body["sources"], list)
