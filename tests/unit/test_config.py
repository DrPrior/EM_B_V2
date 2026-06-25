"""Unit tests for application configuration defaults."""

import pytest

from src.core.config import Settings

pytestmark = pytest.mark.unit


def test_settings_defaults_match_documented_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The container sets CHAT_MODEL/EMBEDDING_MODEL; clear them so this asserts
    # the code defaults (the custom Modelfile variants) rather than the env.
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    settings = Settings()

    assert settings.chat_model == "chat-model"
    assert settings.embedding_model == "embedding-model"
    assert settings.max_history_turns == 10
    assert settings.retrieval_top_k == 5
    assert settings.chunk_max_tokens == 512
    assert settings.chunk_overlap_tokens == 64
    assert settings.vector_retrieval_min_score == 0.75
    assert settings.graph_retrieval_min_score == 0.78
    assert settings.graph_retrieval_limit == 3
    assert settings.rate_limit_per_minute == 20


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TOP_K", "12")
    monkeypatch.setenv("CHAT_MODEL", "custom-model")

    settings = Settings()

    assert settings.retrieval_top_k == 12
    assert settings.chat_model == "custom-model"


def test_settings_case_insensitive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("graph_retrieval_limit", "7")

    settings = Settings()

    assert settings.graph_retrieval_limit == 7
