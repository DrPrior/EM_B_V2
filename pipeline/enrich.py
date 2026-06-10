"""Semantic enrichment pipeline for the Neo4j knowledge graph.

Reads existing Chunk and Document nodes, extracts entities via the local LLM,
and creates Concept, Organization, LegalReference, Course, and MaterialType
nodes with their relationships. Safe to re-run: already-enriched chunks and
documents with an assigned MaterialType are skipped.

Run directly:
    # docker exec -it em_b_v1-api-1 python -m pipeline.enrich
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from neo4j import ManagedTransaction, Session # type: ignore[import-untyped]

from src.database.connection import Neo4jConnection
from src.database import schema
from pipeline.extract import extract_entities, extract_material_type


# ==========================================
# NEO4J TRANSACTION FUNCTIONS
# ==========================================


def _enrich_chunk_tx(
    tx: ManagedTransaction, chunk_id: str, filepath: str, entities: dict
) -> None:
    """Merge all entity nodes for a chunk and create relationships in one transaction."""
    for name in entities["concepts"]:
        tx.run(schema.MERGE_CONCEPT, name=name, description="")
        tx.run(schema.LINK_CHUNK_CONCEPT, chunk_id=chunk_id, name=name)

    for org in entities["organizations"]:
        tx.run(schema.MERGE_ORGANIZATION, name=org["name"], type=org["type"])
        tx.run(schema.LINK_CHUNK_ORGANIZATION, chunk_id=chunk_id, name=org["name"])

    for ref in entities["legal_references"]:
        tx.run(schema.MERGE_LEGAL_REFERENCE, name=ref, citation=ref)
        tx.run(schema.LINK_CHUNK_LEGAL_REF, chunk_id=chunk_id, name=ref)

    for course in entities["courses"]:
        tx.run(schema.MERGE_COURSE, name=course, code="")
        tx.run(schema.LINK_DOC_COURSE, filepath=filepath, name=course)

    tx.run(schema.MARK_CHUNK_ENRICHED, chunk_id=chunk_id)


def _assign_material_type_tx(
    tx: ManagedTransaction, filepath: str, material_type: str
) -> None:
    tx.run(schema.MERGE_MATERIAL_TYPE, name=material_type)
    tx.run(schema.LINK_DOC_MATERIAL_TYPE, filepath=filepath, name=material_type)


# ==========================================
# PROGRESS DISPLAY
# ==========================================


def _print_progress(index: int, total: int, label: str, entity_counts: dict) -> None:
    pct = int(index / total * 100)
    bar_filled = pct // 5
    bar = "#" * bar_filled + "-" * (20 - bar_filled)
    print(f"  [{bar}] {pct:3d}%  ({index:>{len(str(total))}}/{total})  {label}")
    c = entity_counts
    print(
        f"         concepts: {c['concepts']}  orgs: {c['organizations']}  "
        f"refs: {c['legal_references']}  courses: {c['courses']}"
    )


def _print_section(title: str) -> None:
    print(f"\n{'=' * 44}")
    print(f"  {title}")
    print("=" * 44)


def _print_done(stats: dict) -> None:
    width = 44
    print(f"\n{'=' * width}")
    print("  ENRICHMENT COMPLETE")
    print("=" * width)
    print(f"  Documents typed    : {stats['docs_typed']}")
    print(f"  Chunks enriched    : {stats['chunks_enriched']}")
    print(f"  Concepts created   : {stats['concepts']}")
    print(f"  Organizations      : {stats['organizations']}")
    print(f"  Legal references   : {stats['legal_references']}")
    print(f"  Courses            : {stats['courses']}")
    print(f"  Errors             : {stats['errors']}")
    print("=" * width + "\n")


# ==========================================
# ENRICHMENT PASSES
# ==========================================


def enrich_material_types(session: Session, stats: dict) -> None:
    """Assign a MaterialType node to every document that doesn't have one."""
    _print_section("PASS 1 — Document Material Types")

    rows = session.execute_read(
        lambda tx: list(tx.run(schema.FETCH_DOCS_WITHOUT_MATERIAL_TYPE))
    )
    total = len(rows)

    if total == 0:
        print("  All documents already have a material type. Skipping.")
        return

    print(f"  Found {total} untyped documents\n")

    for index, row in enumerate(rows, start=1):
        filepath: str = row["filepath"]
        filename: str = row["filename"] or Path(filepath).name
        first_chunk: str = row["first_chunk_text"] or ""

        try:
            material_type = extract_material_type(filename, first_chunk)
            session.execute_write(_assign_material_type_tx, filepath, material_type)
            stats["docs_typed"] += 1
            pct = int(index / total * 100)
            bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
            print(f"  [{bar}] {pct:3d}%  ({index}/{total})  {filename}  →  {material_type}")
        except Exception as e:
            print(f"  ⚠  [{index}/{total}] Failed for {filename}: {e}")
            stats["errors"] += 1


def enrich_chunks(session: Session, stats: dict) -> None:
    """Extract and link entities for every unenriched Chunk node."""
    _print_section("PASS 2 — Chunk Entity Extraction")

    rows = session.execute_read(
        lambda tx: list(tx.run(schema.FETCH_UNENRICHED_CHUNKS))
    )
    total = len(rows)

    if total == 0:
        print("  All chunks already enriched. Skipping.")
        return

    print(f"  Found {total} unenriched chunks\n")

    for index, row in enumerate(rows, start=1):
        chunk_id: str = row["chunk_id"]
        text: str = row["text"] or ""
        filepath: str = row["filepath"]
        filename: str = row["filename"] or Path(filepath).name

        try:
            entities = extract_entities(text)
            session.execute_write(_enrich_chunk_tx, chunk_id, filepath, entities)

            stats["chunks_enriched"] += 1
            stats["concepts"] += len(entities["concepts"])
            stats["organizations"] += len(entities["organizations"])
            stats["legal_references"] += len(entities["legal_references"])
            stats["courses"] += len(entities["courses"])

            _print_progress(index, total, filename, {
                "concepts": len(entities["concepts"]),
                "organizations": len(entities["organizations"]),
                "legal_references": len(entities["legal_references"]),
                "courses": len(entities["courses"]),
            })

        except Exception as e:
            print(f"  ⚠  [{index}/{total}] Chunk {chunk_id[:8]}... failed: {e}")
            stats["errors"] += 1


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================


def enrich_project_data(session: Session) -> dict:
    """Run both enrichment passes against the existing graph.

    Returns a statistics dictionary.
    """
    stats = {
        "docs_typed": 0,
        "chunks_enriched": 0,
        "concepts": 0,
        "organizations": 0,
        "legal_references": 0,
        "courses": 0,
        "errors": 0,
    }

    print("Starting semantic enrichment pipeline...")

    enrich_material_types(session, stats)
    enrich_chunks(session, stats)
    _print_done(stats)

    return stats


if __name__ == "__main__":
    nc = Neo4jConnection.get_instance()
    try:
        with nc.session() as session:
            enrich_project_data(session)
    finally:
        nc.close()
