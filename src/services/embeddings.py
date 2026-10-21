import requests
from neo4j import ManagedTransaction, Session  # type: ignore[import-untyped]

from src.core.config import settings
from src.core.timing import log_ollama, parse_ollama_timings
from src.services.llm import raise_for_ollama


def generate_embedding(text: str, session_id: str | None = None) -> list[float]:
    """Generates a vector embedding for a given string using Ollama's API."""
    url = f"{settings.ollama_base_url}/api/embeddings"
    payload = {"model": settings.embedding_model, "prompt": text}

    response = requests.post(url, json=payload)
    raise_for_ollama(response)

    body = response.json()
    log_ollama(
        "embeddings", settings.embedding_model, parse_ollama_timings(body), session_id
    )
    # Ollama returns a JSON object with an 'embedding' array
    return body.get("embedding", [])


# embeddinggemma's prompt for the query side of retrieval. Stored chunks are
# embedded as raw text (ingest.py, reembed.py); only questions get this prefix.
# Measured on the dev corpus: it lifts on-topic top-1 scores (median 0.795 →
# 0.819) and drops off-topic ones (max 0.740 → 0.605), so a cutoff can separate
# them; without it the two ranges overlap. The retrieval cutoffs in config.py
# are calibrated for prefixed questions — change both together.
QUERY_PREFIX = "task: search result | query: "


def generate_query_embedding(
    question: str, session_id: str | None = None
) -> list[float]:
    """Embed a user question for retrieval against the stored chunk embeddings.

    Args:
        question: The user's question (or search text).
        session_id: Conversation id used to correlate timing logs across stages.

    Returns:
        The question's embedding vector.
    """
    return generate_embedding(f"{QUERY_PREFIX}{question}", session_id=session_id)


def _store_embedding_tx(
    tx: ManagedTransaction, chunk_id: str, embedding: list[float]
) -> None:
    """Transaction function to store the embedding vector on a Chunk node.

    Args:
        tx: Neo4j managed transaction object.
        chunk_id: The unique identifier for the chunk.
        embedding: The vector embedding list to store.
    """
    query = """
    MATCH (c:Chunk {chunk_id: $chunk_id})
    SET c.embedding = $embedding
    """
    tx.run(query, chunk_id=chunk_id, embedding=embedding)


def embed_and_store_chunk(text: str, chunk_id: str, session: Session) -> None:
    """Generates an embedding for a text chunk and stores it in Neo4j.

    Args:
        text: The text content to embed.
        chunk_id: The unique identifier of the target Chunk node.
        session: An active Neo4j database session.
    """
    embedding_vector = generate_embedding(text)
    if embedding_vector:
        session.execute_write(
            _store_embedding_tx, chunk_id=chunk_id, embedding=embedding_vector
        )
