"""Unit tests for the per-stage timing helpers."""

import pytest

from src.core.timing import parse_ollama_timings, timed

pytestmark = pytest.mark.unit


def test_parse_ollama_timings_converts_ns_to_ms() -> None:
    payload = {
        "total_duration": 5_600_000_000,
        "load_duration": 12_000_000,
        "prompt_eval_duration": 480_000_000,
        "eval_duration": 5_100_000_000,
        "prompt_eval_count": 312,
        "eval_count": 420,
    }

    timings = parse_ollama_timings(payload)

    assert timings["total_ms"] == 5600.0
    assert timings["load_ms"] == 12.0
    assert timings["prompt_eval_ms"] == 480.0
    assert timings["eval_ms"] == 5100.0
    assert timings["prompt_eval_count"] == 312
    assert timings["eval_count"] == 420
    # 420 tokens / 5.1 s ≈ 82.4 tok/s
    assert timings["tokens_per_sec"] == pytest.approx(82.4, abs=0.1)


def test_parse_ollama_timings_tolerates_missing_keys() -> None:
    # The /api/embeddings endpoint returns far fewer fields.
    timings = parse_ollama_timings({})

    assert timings["total_ms"] is None
    assert timings["load_ms"] is None
    assert timings["eval_count"] is None
    # No eval_count/duration → no tokens_per_sec, and no ZeroDivisionError.
    assert timings["tokens_per_sec"] is None


def test_parse_ollama_timings_no_divide_by_zero_on_zero_duration() -> None:
    timings = parse_ollama_timings({"eval_count": 10, "eval_duration": 0})

    assert timings["tokens_per_sec"] is None


def test_timed_records_elapsed_ms() -> None:
    stage_ms: dict[str, float] = {}

    with timed("embed", stage_ms):
        pass

    assert "embed" in stage_ms
    assert isinstance(stage_ms["embed"], float)
    assert stage_ms["embed"] >= 0.0


def test_timed_records_even_on_exception() -> None:
    stage_ms: dict[str, float] = {}

    with pytest.raises(ValueError):
        with timed("graph_query", stage_ms):
            raise ValueError("boom")

    assert "graph_query" in stage_ms
