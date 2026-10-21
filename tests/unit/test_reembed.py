"""Unit tests for the re-embed pipeline (Neo4j faked in memory, Ollama mocked)."""

import logging

import pytest

from pipeline import reembed
from src.database import schema

pytestmark = pytest.mark.unit

DIMS = schema.EMBEDDING_DIMENSIONS


class _Record(dict):
    def data(self) -> dict:
        return dict(self)


class _FakeGraph:
    """Just enough of a Neo4j session to run the re-embed queries."""

    def __init__(self, chunks: dict[str, list[float] | None]) -> None:
        self.embeddings = dict(chunks)
        self.writes = 0

    def run(self, query: str, **params) -> list[_Record]:
        if query == schema.COUNT_CHUNK_EMBEDDING_SIZES:
            sizes: dict[int | None, int] = {}
            for emb in self.embeddings.values():
                dims = None if emb is None else len(emb)
                sizes[dims] = sizes.get(dims, 0) + 1
            return [_Record(dims=d, n=n) for d, n in sizes.items()]
        if query == schema.FETCH_CHUNKS_TO_REEMBED:
            todo = [
                _Record(chunk_id=cid, text=f"text of {cid}")
                for cid, emb in sorted(self.embeddings.items())
                if (emb is None or len(emb) != params["dims"])
                and cid not in params["skip"]
            ]
            return todo[: params["limit"]]
        if query == schema.SET_CHUNK_EMBEDDINGS:
            self.writes += 1
            for row in params["rows"]:
                self.embeddings[row["chunk_id"]] = row["embedding"]
            return []
        raise AssertionError(f"unexpected query: {query}")

    # Session API: managed transactions call fn(tx, **kwargs).
    def execute_read(self, fn, **kwargs):
        return fn(self, **kwargs)

    def execute_write(self, fn, **kwargs):
        return fn(self, **kwargs)


def _graph(old: int = 0, missing: int = 0, good: int = 0) -> _FakeGraph:
    chunks: dict[str, list[float] | None] = {}
    chunks.update({f"old{i:02}": [0.1] * 2560 for i in range(old)})
    chunks.update({f"none{i:02}": None for i in range(missing)})
    chunks.update({f"good{i:02}": [0.5] * DIMS for i in range(good)})
    return _FakeGraph(chunks)


@pytest.fixture
def embed_calls(monkeypatch) -> list[str]:
    calls: list[str] = []

    def _fake_embed(text: str, session_id: str | None = None) -> list[float]:
        calls.append(text)
        return [0.9] * DIMS

    monkeypatch.setattr(reembed, "generate_embedding", _fake_embed)
    return calls


def test_reembeds_wrong_size_and_missing_but_not_good(embed_calls) -> None:
    graph = _graph(old=7, missing=2, good=3)

    stats = reembed.reembed_chunks(graph, batch_size=4)

    assert stats == {"reembedded": 9, "errors": 0, "remaining": 0}
    assert len(embed_calls) == 9
    assert all(len(e) == DIMS for e in graph.embeddings.values())
    # Already-good chunks are left exactly as they were.
    assert graph.embeddings["good00"] == [0.5] * DIMS
    assert graph.writes == 3  # batches of 4, 4, 1


def test_limit_stops_early_and_rerun_resumes(embed_calls) -> None:
    graph = _graph(old=10)

    first = reembed.reembed_chunks(graph, limit=4, batch_size=3)
    assert first == {"reembedded": 4, "errors": 0, "remaining": 6}

    second = reembed.reembed_chunks(graph)
    assert second == {"reembedded": 6, "errors": 0, "remaining": 0}
    assert len(embed_calls) == 10  # nothing embedded twice


def test_failed_chunk_is_skipped_not_refetched(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="em_b")
    graph = _graph(old=5)
    calls: list[str] = []

    def _flaky(text: str, session_id: str | None = None) -> list[float]:
        calls.append(text)
        if text == "text of old02":
            raise RuntimeError("Ollama hiccup")
        return [0.9] * DIMS

    monkeypatch.setattr(reembed, "generate_embedding", _flaky)

    stats = reembed.reembed_chunks(graph, batch_size=2)

    assert stats == {"reembedded": 4, "errors": 1, "remaining": 1}
    assert calls.count("text of old02") == 1
    assert len(graph.embeddings["old02"]) == 2560
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "old02" in warning.getMessage()
    assert warning.exc_info is not None


def test_stops_when_a_whole_batch_fails(monkeypatch, caplog) -> None:
    caplog.set_level(logging.ERROR, logger="em_b")
    graph = _graph(old=20)
    calls: list[str] = []

    def _down(text: str, session_id: str | None = None) -> list[float]:
        calls.append(text)
        raise ConnectionError("Ollama is down")

    monkeypatch.setattr(reembed, "generate_embedding", _down)

    stats = reembed.reembed_chunks(graph, batch_size=5)

    # One failed batch, then it gives up instead of trying all 20.
    assert len(calls) == 5
    assert stats == {"reembedded": 0, "errors": 5, "remaining": 20}
    assert any("stopping" in r.getMessage() for r in caplog.records)


def test_wrong_size_from_model_raises_and_writes_nothing(monkeypatch) -> None:
    graph = _graph(old=3)
    monkeypatch.setattr(reembed, "generate_embedding", lambda *a, **k: [0.1] * 2560)

    with pytest.raises(reembed.EmbeddingSizeError, match="2560-d"):
        reembed.reembed_chunks(graph)

    assert graph.writes == 0


def test_count_chunks_to_reembed() -> None:
    assert reembed.count_chunks_to_reembed(_graph(old=4, missing=1, good=6)) == 5
    assert reembed.count_chunks_to_reembed(_graph(good=6)) == 0


def test_nothing_to_do_is_a_noop(embed_calls) -> None:
    graph = _graph(good=4)

    stats = reembed.reembed_chunks(graph)

    assert stats == {"reembedded": 0, "errors": 0, "remaining": 0}
    assert embed_calls == []
    assert graph.writes == 0
