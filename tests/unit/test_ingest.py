"""Unit tests for ingestion helpers (file I/O + chunking + graph checks)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.ingest import (
    chunk_text,
    clear_file_chunks,
    discover_files,
    estimate_tokens,
    is_file_embedded,
    read_file_content,
)

pytestmark = pytest.mark.unit


def test_estimate_tokens_uses_four_char_ratio() -> None:
    assert estimate_tokens("a" * 40) == 10
    assert estimate_tokens("") == 0


def test_discover_files_filters_and_sorts(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "ignore.png").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.pdf").write_text("x")

    found = discover_files(str(tmp_path))

    names = [Path(f).name for f in found]
    assert "ignore.png" not in names
    assert names == sorted(names)
    assert {"a.md", "b.txt", "c.pdf"} == set(names)


def test_discover_files_missing_root_returns_empty() -> None:
    assert discover_files("/no/such/path/here") == []


def test_read_file_content_reads_text(tmp_path: Path) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("hello world", encoding="utf-8")

    assert read_file_content(str(f)) == "hello world"


def test_read_file_content_unsupported_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "data.csv"
    f.write_text("a,b,c")

    assert read_file_content(str(f)) is None


def test_chunk_text_short_text_single_chunk() -> None:
    chunks = chunk_text("One short sentence.", max_chunk_size=512, overlap=64)

    assert chunks == ["One short sentence."]


def test_chunk_text_splits_long_text() -> None:
    # ~50 sentences, each ~25 chars; well over a tiny chunk budget.
    text = " ".join(f"Sentence number {i} here." for i in range(50))
    chunks = chunk_text(text, max_chunk_size=20, overlap=4)  # 80-char budget

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)  # no empty chunks


def test_chunk_text_empty_input_returns_empty() -> None:
    assert chunk_text("   ", max_chunk_size=512, overlap=64) == []


def test_is_file_embedded_true() -> None:
    session = MagicMock()
    session.execute_read.return_value = {"embedded": True}

    assert is_file_embedded(session, "/app/project_data/a.txt") is True


def test_is_file_embedded_false() -> None:
    session = MagicMock()
    session.execute_read.return_value = {"embedded": False}

    assert is_file_embedded(session, "/app/project_data/a.txt") is False


def test_is_file_embedded_no_result() -> None:
    session = MagicMock()
    session.execute_read.return_value = None

    assert is_file_embedded(session, "/app/project_data/a.txt") is False


def test_clear_file_chunks_issues_write() -> None:
    session = MagicMock()

    clear_file_chunks(session, "/app/project_data/a.txt")

    session.execute_write.assert_called_once()
