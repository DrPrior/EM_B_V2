"""Per-stage query timing instrumentation.

Emits structured timing lines to the ``em_b.timing`` logger so the latency of
each stage of a chat query can be attributed without changing any public API.

Two complementary kinds of line are produced, correlated by ``session_id``:

- ``ollama call=… …`` lines (one per Ollama HTTP call) carry the model's own
  internal timings (``load_duration``/``prompt_eval_duration``/``eval_duration``)
  so model-load can be separated from prompt-eval and token generation.
- ``rag stages …`` lines carry wall-clock durations of each retrieval stage.

All helpers no-op when ``settings.timing_log_enabled`` is false.
"""

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from src.core.config import settings

logger = logging.getLogger("em_b.timing")

# Attach a stdout handler once, only if the root logger isn't already
# configured, so timing lines show up in `docker logs em_b_v2-api-1` alongside
# uvicorn output without double-logging when a handler chain already exists.
if not logger.handlers and not logging.getLogger().handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

logger.setLevel(settings.timing_log_level.upper())


def _ms(nanoseconds: float | None) -> float | None:
    """Convert a nanosecond duration to milliseconds, rounded to one decimal."""
    if nanoseconds is None:
        return None
    return round(nanoseconds / 1_000_000, 1)


def _sid(session_id: str | None) -> str:
    """Short, log-friendly form of a session id (first 8 chars)."""
    return (session_id or "-")[:8]


def parse_ollama_timings(payload: dict) -> dict[str, float | int | None]:
    """Extract Ollama's internal timing fields from a response body.

    Ollama returns durations in nanoseconds. The ``/api/embeddings`` endpoint
    returns fewer fields than ``/api/generate`` and ``/api/chat``; missing keys
    are tolerated and returned as ``None``.

    Args:
        payload: The parsed JSON body of an Ollama API response.

    Returns:
        A dict with millisecond durations (``total_ms``, ``load_ms``,
        ``prompt_eval_ms``, ``eval_ms``), token counts (``prompt_eval_count``,
        ``eval_count``), and a derived ``tokens_per_sec``.
    """
    eval_count = payload.get("eval_count")
    eval_duration = payload.get("eval_duration")
    tokens_per_sec: float | None = None
    if eval_count and eval_duration:
        tokens_per_sec = round(eval_count / (eval_duration / 1_000_000_000), 1)

    return {
        "total_ms": _ms(payload.get("total_duration")),
        "load_ms": _ms(payload.get("load_duration")),
        "prompt_eval_ms": _ms(payload.get("prompt_eval_duration")),
        "eval_ms": _ms(payload.get("eval_duration")),
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": eval_count,
        "tokens_per_sec": tokens_per_sec,
    }


def log_ollama(
    call: str,
    model: str,
    timings: dict,
    session_id: str | None = None,
) -> None:
    """Emit one ``ollama call=…`` timing line for a single Ollama HTTP call.

    Args:
        call: Which endpoint was hit — ``embeddings`` | ``generate`` | ``chat``.
        model: The Ollama model name used.
        timings: The dict returned by :func:`parse_ollama_timings`.
        session_id: Conversation id used to correlate lines across stages.
    """
    if not settings.timing_log_enabled:
        return

    prompt_tok = timings.get("prompt_eval_count")
    eval_tok = timings.get("eval_count")
    tps = timings.get("tokens_per_sec")
    prompt_part = (
        f"prompt_eval={timings.get('prompt_eval_ms')}ms({prompt_tok}tok)"
        if prompt_tok is not None
        else f"prompt_eval={timings.get('prompt_eval_ms')}ms"
    )
    eval_part = (
        f"eval={timings.get('eval_ms')}ms({eval_tok}tok,{tps}tok/s)"
        if eval_tok is not None
        else f"eval={timings.get('eval_ms')}ms"
    )
    logger.info(
        "ollama call=%s model=%s load=%sms %s %s total=%sms sid=%s",
        call,
        model,
        timings.get("load_ms"),
        prompt_part,
        eval_part,
        timings.get("total_ms"),
        _sid(session_id),
    )


@contextmanager
def timed(stage: str, stage_ms: dict[str, float]) -> Iterator[None]:
    """Time a block of work and record its wall-clock ms under ``stage``.

    Args:
        stage: Key to store the elapsed time under in ``stage_ms``.
        stage_ms: Caller-owned dict the duration is written into.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        stage_ms[stage] = round((time.perf_counter() - start) * 1000, 1)


def log_rag_stages(stage_ms: dict[str, float], session_id: str | None = None) -> None:
    """Emit one consolidated ``rag stages …`` wall-clock line for a query.

    Args:
        stage_ms: Mapping of stage name to elapsed milliseconds.
        session_id: Conversation id used to correlate with the ollama lines.
    """
    if not settings.timing_log_enabled:
        return

    parts = " ".join(f"{name}={ms}ms" for name, ms in stage_ms.items())
    total = round(sum(stage_ms.values()), 1)
    logger.info(
        "rag stages sid=%s %s retrieval_total=%sms", _sid(session_id), parts, total
    )
