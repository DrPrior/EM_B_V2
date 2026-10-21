"""Re-embed Chunk nodes whose embeddings don't fit the vector index.

The vector index (``chunk_vector_idx``) is built for
``schema.EMBEDDING_DIMENSIONS`` (768, embeddinggemma). Neo4j silently leaves out
any chunk whose embedding has another size, so a graph embedded by an earlier
model (the pre-September graph used qwen3-embedding:4b at 2560-d) retrieves
nothing and every answer says there is not enough context.

This recomputes those embeddings from each chunk's stored text with the current
``embedding-model``, embedding the raw chunk text exactly as ``ingest.py`` does.
Nothing else changes: chunks keep their ids, entity links and file metadata, so
no re-ingest or re-enrichment (the expensive LLM pass) is needed. Chunks with no
embedding at all are filled in too.

Idempotent and resumable: each batch selects only chunks that still need it, so
an interrupted run picks up where it stopped. Calls Ollama one at a time.

Run directly (with ``.env`` loaded into the process, as ``scripts/dev-up.ps1``
does):
    python -m pipeline.reembed --dry-run    # count what needs re-embedding
    python -m pipeline.reembed --limit 20   # trial run on 20 chunks
    python -m pipeline.reembed              # everything
"""

import argparse
import logging
import time

from neo4j import ManagedTransaction, Session  # type: ignore[import-untyped]

from src.core.logging_config import configure_logging
from src.database import schema
from src.database.connection import Neo4jConnection
from src.services.embeddings import generate_embedding

logger = logging.getLogger("em_b.reembed")

DEFAULT_BATCH_SIZE = 50


class EmbeddingSizeError(RuntimeError):
    """embedding-model returned a vector of the wrong size.

    That means the model itself is misconfigured, so every chunk would get a
    vector the index can't use. The run stops rather than write any of them.
    """


def _fetch_batch(
    tx: ManagedTransaction, limit: int, skip: list[str]
) -> list[dict[str, str]]:
    result = tx.run(
        schema.FETCH_CHUNKS_TO_REEMBED,
        dims=schema.EMBEDDING_DIMENSIONS,
        skip=skip,
        limit=limit,
    )
    return [record.data() for record in result]


def _store_batch(tx: ManagedTransaction, rows: list[dict]) -> None:
    tx.run(schema.SET_CHUNK_EMBEDDINGS, rows=rows)


def count_chunks_to_reembed(session: Session) -> int:
    """Return how many chunks have a missing or wrong-size embedding.

    Args:
        session: An open Neo4j session.

    Returns:
        Number of chunks the vector index can't currently use.
    """
    sizes = session.execute_read(
        lambda tx: list(tx.run(schema.COUNT_CHUNK_EMBEDDING_SIZES))
    )
    return sum(
        record["n"] for record in sizes if record["dims"] != schema.EMBEDDING_DIMENSIONS
    )


def reembed_chunks(
    session: Session,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Re-embed chunks whose embedding is missing or the wrong size.

    Args:
        session: An open Neo4j session with write access.
        limit: Stop after this many chunks (``None`` = all of them).
        batch_size: Chunks fetched, embedded and written per transaction.

    Returns:
        Stats: ``reembedded`` (stored), ``errors`` (failed and skipped) and
        ``remaining`` (still unusable afterwards).

    Raises:
        EmbeddingSizeError: embedding-model returned the wrong vector size.
    """
    target = count_chunks_to_reembed(session)
    if limit is not None:
        target = min(target, limit)
    logger.info("Re-embedding %d chunks to %d-d", target, schema.EMBEDDING_DIMENSIONS)

    stats = {"reembedded": 0, "errors": 0}
    failed: list[str] = []
    started = time.monotonic()

    while stats["reembedded"] + stats["errors"] < target:
        want = min(batch_size, target - stats["reembedded"] - stats["errors"])
        batch = session.execute_read(_fetch_batch, limit=want, skip=failed)
        if not batch:
            break

        rows: list[dict] = []
        for chunk in batch:
            try:
                embedding = generate_embedding(chunk["text"])
            except Exception:
                logger.warning(
                    "Embedding chunk %s failed; skipping it",
                    chunk["chunk_id"],
                    exc_info=True,
                )
                failed.append(chunk["chunk_id"])
                stats["errors"] += 1
                continue
            if len(embedding) != schema.EMBEDDING_DIMENSIONS:
                raise EmbeddingSizeError(
                    f"embedding-model returned {len(embedding)}-d vectors, but the "
                    f"index needs {schema.EMBEDDING_DIMENSIONS}-d. Check that the "
                    f"model is built FROM embeddinggemma (Modelfile.embeddings)."
                )
            rows.append({"chunk_id": chunk["chunk_id"], "embedding": embedding})

        if not rows:
            # A whole batch failed: Ollama is down or wedged. Stop instead of
            # burning through every remaining chunk with the same error.
            logger.error(
                "Every chunk in the last batch failed to embed; stopping. "
                "Re-run once Ollama is healthy to resume."
            )
            break

        session.execute_write(_store_batch, rows=rows)
        stats["reembedded"] += len(rows)
        elapsed = time.monotonic() - started
        logger.info(
            "Re-embedded %d/%d chunks (%.1f chunks/s, %d errors)",
            stats["reembedded"],
            target,
            stats["reembedded"] / elapsed if elapsed else 0.0,
            stats["errors"],
        )

    stats["remaining"] = count_chunks_to_reembed(session)
    logger.info(
        "Done: %d re-embedded, %d errors, %d chunks still unusable",
        stats["reembedded"],
        stats["errors"],
        stats["remaining"],
    )
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-embed chunks whose embeddings don't fit the vector index."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after this many chunks."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Chunks per write transaction (default {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count the chunks that need re-embedding.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    # Install the shared handler (console, plus logs/errors.log in dev) so the
    # progress and failure records aren't dropped.
    configure_logging()
    nc = Neo4jConnection.get_instance()
    try:
        with nc.session() as session:
            if args.dry_run:
                logger.info(
                    "%d chunks need re-embedding", count_chunks_to_reembed(session)
                )
            else:
                reembed_chunks(session, limit=args.limit, batch_size=args.batch_size)
    finally:
        nc.close()
