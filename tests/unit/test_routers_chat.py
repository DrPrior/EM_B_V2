"""Unit tests for the chat router (RAG service + Neo4j mocked)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from src.main import app
from src.routers import chat as chat_router

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    # Plain instantiation (no ``with``) skips the lifespan handler, so no real
    # Neo4j connection is opened during unit tests.
    app.dependency_overrides[chat_router.get_db_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_success(client: TestClient) -> None:
    with patch.object(
        chat_router.rag_service,
        "answer_question",
        return_value=("sid-1", "an answer", [{"filename": "a.pdf", "score": 0.9}]),
    ):
        resp = client.post("/chat/", json={"question": "What is EM?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "an answer"
    assert body["session_id"] == "sid-1"
    # The Source model always serialises superseded_by (null when not superseded).
    assert body["sources"] == [
        {"filename": "a.pdf", "score": 0.9, "superseded_by": None}
    ]


def test_chat_empty_question_rejected(client: TestClient) -> None:
    resp = client.post("/chat/", json={"question": "   "})

    assert resp.status_code == 422


def test_chat_service_http_exception_propagates(client: TestClient) -> None:
    with patch.object(
        chat_router.rag_service,
        "answer_question",
        side_effect=HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="boom"
        ),
    ):
        resp = client.post("/chat/", json={"question": "hi"})

    assert resp.status_code == 500


def test_chat_unexpected_error_becomes_500(client: TestClient) -> None:
    with patch.object(
        chat_router.rag_service,
        "answer_question",
        side_effect=RuntimeError("kaboom"),
    ):
        resp = client.post("/chat/", json={"question": "hi"})

    assert resp.status_code == 500


def test_chat_stream_emits_sse_events(client: TestClient) -> None:
    with patch.object(
        chat_router.rag_service,
        "stream_answer",
        return_value=("sid-9", [{"filename": "a.pdf", "score": 0.9}], iter(["A", "B"])),
    ):
        resp = client.post("/chat/stream", json={"question": "hi"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert '"type": "metadata"' in body
    assert '"session_id": "sid-9"' in body
    assert '"type": "token"' in body
    assert '"type": "done"' in body


def test_get_history_found(client: TestClient) -> None:
    history = [{"role": "user", "content": "q"}]
    with patch.object(
        chat_router.conversation_store, "get_history", return_value=history
    ):
        resp = client.get("/chat/sessions/abc/history")

    assert resp.status_code == 200
    assert resp.json() == {"session_id": "abc", "history": history}


def test_get_history_not_found(client: TestClient) -> None:
    with patch.object(
        chat_router.conversation_store, "get_history", return_value=None
    ):
        resp = client.get("/chat/sessions/abc/history")

    assert resp.status_code == 404


def test_delete_session_success(client: TestClient) -> None:
    with patch.object(
        chat_router.conversation_store, "delete_session", return_value=True
    ):
        resp = client.delete("/chat/sessions/abc")

    assert resp.status_code == 204


def test_delete_session_not_found(client: TestClient) -> None:
    with patch.object(
        chat_router.conversation_store, "delete_session", return_value=False
    ):
        resp = client.delete("/chat/sessions/abc")

    assert resp.status_code == 404
