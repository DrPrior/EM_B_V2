"""Unit tests for the enrichment pipeline's parallel Pass 2 (Neo4j + LLM mocked)."""

from unittest.mock import MagicMock

import pytest

from pipeline import enrich

pytestmark = pytest.mark.unit


def _rows(n: int) -> list[dict]:
    return [
        {
            "chunk_id": f"c{i}",
            "text": f"chunk text {i}",
            "filepath": f"/app/project_data/f{i}.pdf",
            "filename": f"f{i}.pdf",
        }
        for i in range(n)
    ]


def _fresh_stats() -> dict:
    return dict.fromkeys(
        (
            "docs_typed",
            "chunks_enriched",
            "concepts",
            "organizations",
            "legal_references",
            "courses",
            "errors",
        ),
        0,
    )


@pytest.mark.parametrize("workers", [1, 4])
def test_enrich_chunks_processes_all_and_aggregates(monkeypatch, workers) -> None:
    """Every chunk is written exactly once and stats sum correctly, at any
    concurrency (the LLM calls parallelize; the writes stay serial here)."""
    rows = _rows(12)
    session = MagicMock()
    session.execute_read.return_value = rows

    written: list[tuple[str, dict]] = []
    session.execute_write.side_effect = lambda _fn, chunk_id, filepath, entities: (
        written.append((chunk_id, entities))
    )

    entities = {
        "concepts": ["A", "B"],
        "organizations": [{"name": "FEMA", "type": "agency"}],
        "legal_references": [],
        "courses": [],
    }
    # extract_entities takes (text, session_id=None); return a fresh copy each call.
    def _fake_extract(text, *args, **kwargs):
        return {key: list(val) for key, val in entities.items()}

    monkeypatch.setattr(enrich, "extract_entities", _fake_extract)
    monkeypatch.setattr(enrich.settings, "enrichment_concurrency", workers)

    stats = _fresh_stats()
    enrich.enrich_chunks(session, stats)

    assert stats["chunks_enriched"] == 12
    assert stats["concepts"] == 24  # 2 per chunk
    assert stats["organizations"] == 12
    assert stats["errors"] == 0
    # Each chunk written exactly once, none dropped or duplicated.
    assert {c for c, _ in written} == {f"c{i}" for i in range(12)}
    assert len(written) == 12


def test_enrich_chunks_empty_is_noop(monkeypatch) -> None:
    session = MagicMock()
    session.execute_read.return_value = []
    monkeypatch.setattr(enrich, "extract_entities", lambda *a, **k: {})
    stats = _fresh_stats()

    enrich.enrich_chunks(session, stats)

    assert stats["chunks_enriched"] == 0
    session.execute_write.assert_not_called()
