import requests
from neo4j import ManagedTransaction, Session  # type: ignore[import-untyped]

from src.core.config import settings


def generate_embedding(text: str) -> list[float]:
    """Generates a vector embedding for a given string using Ollama's API."""
    url = f"{settings.ollama_base_url}/api/embeddings"
    payload = {"model": settings.embedding_model, "prompt": text}

    response = requests.post(url, json=payload)
    response.raise_for_status()  # Raise an error if the request fails

    # Ollama returns a JSON object with an 'embedding' array
    return response.json().get("embedding", [])


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
