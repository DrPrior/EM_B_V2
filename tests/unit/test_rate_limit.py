"""Unit tests for per-IP rate limiting on the chat endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.config import settings
from src.main import app
from src.routers import chat as chat_router

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    app.dependency_overrides[chat_router.get_db_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_requests_within_limit_pass(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)

    with patch.object(
        chat_router.rag_service,
        "answer_question",
        return_value=("sid-1", "ok", []),
    ):
        statuses = [
            client.post("/chat/", json={"question": "hi"}).status_code for _ in range(3)
        ]

    assert statuses == [200, 200, 200]


def test_request_over_limit_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)

    with patch.object(
        chat_router.rag_service,
        "answer_question",
        return_value=("sid-1", "ok", []),
    ):
        first = client.post("/chat/", json={"question": "hi"})
        second = client.post("/chat/", json={"question": "hi"})
        third = client.post("/chat/", json={"question": "hi"})

    assert first.status_code == 200
    assert second.status_code == 200
    # The third call within the same minute exceeds the per-IP limit.
    assert third.status_code == 429
