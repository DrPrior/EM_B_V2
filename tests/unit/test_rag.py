"""Unit tests for the RAG retrieval pipeline (Neo4j + Ollama mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.rag import RAGService
from src.services.session import ConversationStore

pytestmark = pytest.mark.unit


EMPTY_ENTITIES = {
    "concepts": [],
    "organizations": [],
    "legal_references": [],
    "courses": [],
}


def _vector_record(chunk_id: str, text: str, score: float, filename: str) -> dict:
    return {"chunk_id": chunk_id, "text": text, "score": score, "filename": filename}


@pytest.fixture
def isolated_store():
    """Replace the module-level conversation store with a fresh one."""
    store = ConversationStore(max_turns=10)
    with patch("src.services.rag.conversation_store", store):
        yield store


def test_vector_only_retrieval_builds_context(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [
        _vector_record("c1", "Emergency management basics.", 0.9, "FEMA.pdf"),
    ]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
    ):
        sid, messages, sources = service._retrieve_and_build_messages(
            "What is EM?", db, None
        )

    # No entities -> graph query never runs (single db call).
    assert db.run.call_count == 1
    assert sid
    assert messages[0]["role"] == "system"
    assert "FEMA.pdf" in messages[-1]["content"]
    assert "Emergency management basics." in messages[-1]["content"]
    assert sources == [{"filename": "FEMA.pdf", "score": 0.9}]


def test_vector_results_below_min_score_excluded(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [
        _vector_record("c1", "high", 0.9, "a.pdf"),
        _vector_record("c2", "low", 0.5, "b.pdf"),  # below 0.75 floor
    ]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
    ):
        _, _, sources = service._retrieve_and_build_messages("q", db, None)

    assert sources == [{"filename": "a.pdf", "score": 0.9}]


def test_graph_results_appended_after_vector(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.side_effect = [
        [_vector_record("c1", "vector chunk", 0.9, "vec.pdf")],
        [
            {
                "chunk_id": "c2",
                "text": "graph chunk",
                "filename": "graph.pdf",
                "score": 0.88,
            }
        ],
    ]
    entities = {
        "concepts": ["ICS"],
        "organizations": [],
        "legal_references": [],
        "courses": [],
    }

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=entities),
    ):
        _, _, sources = service._retrieve_and_build_messages("q", db, None)

    assert db.run.call_count == 2  # vector + graph
    assert sources == [
        {"filename": "vec.pdf", "score": 0.9},
        {"filename": "graph.pdf", "score": 0.88},
    ]


def test_duplicate_chunk_id_deduped(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.side_effect = [
        [_vector_record("dup", "same text", 0.9, "vec.pdf")],
        [
            {
                "chunk_id": "dup",
                "text": "same text",
                "filename": "graph.pdf",
                "score": 0.88,
            }
        ],
    ]
    entities = {
        "concepts": ["ICS"],
        "organizations": [],
        "legal_references": [],
        "courses": [],
    }

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=entities),
    ):
        _, _, sources = service._retrieve_and_build_messages("q", db, None)

    assert sources == [{"filename": "vec.pdf", "score": 0.9}]


def test_graph_failure_degrades_to_vector_only(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [_vector_record("c1", "vector chunk", 0.9, "vec.pdf")]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch(
            "src.services.rag.extract_entities",
            side_effect=RuntimeError("LLM down"),
        ),
    ):
        _, _, sources = service._retrieve_and_build_messages("q", db, None)

    assert sources == [{"filename": "vec.pdf", "score": 0.9}]


def test_no_context_produces_fallback_prompt(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = []

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
    ):
        _, messages, sources = service._retrieve_and_build_messages("q", db, None)

    assert sources == []
    assert "No relevant context" in messages[-1]["content"]


def test_superseded_source_is_annotated_not_filtered(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [
        {
            "chunk_id": "c1",
            "text": "Older EOP guidance.",
            "score": 0.9,
            "filename": "CPG_101_V2.pdf",
            "superseders": ["CPG-101: Developing & Maintaining EOPs"],
        },
    ]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
    ):
        _, messages, sources = service._retrieve_and_build_messages("q", db, None)

    # Still retrieved (not filtered) and flagged with the superseding title.
    assert sources == [
        {
            "filename": "CPG_101_V2.pdf",
            "score": 0.9,
            "superseded_by": "CPG-101: Developing & Maintaining EOPs",
        }
    ]
    content = messages[-1]["content"]
    assert "SUPERSEDED by CPG-101: Developing & Maintaining EOPs" in content
    assert "historical reference" in content
    assert "Older EOP guidance." in content


def test_non_superseded_source_omits_supersede_field(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [
        {
            "chunk_id": "c1",
            "text": "Current guidance.",
            "score": 0.9,
            "filename": "NIMS.pdf",
            "superseders": [],
        },
    ]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
    ):
        _, messages, sources = service._retrieve_and_build_messages("q", db, None)

    assert sources == [{"filename": "NIMS.pdf", "score": 0.9}]
    assert "SUPERSEDED" not in messages[-1]["content"]


def test_multiple_superseders_deduped_and_joined(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [
        {
            "chunk_id": "c1",
            "text": "old",
            "score": 0.9,
            "filename": "old.pdf",
            "superseders": ["Edition B", "Edition B", "Edition C"],
        },
    ]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
    ):
        _, _, sources = service._retrieve_and_build_messages("q", db, None)

    assert sources[0]["superseded_by"] == "Edition B / Edition C"


def test_embedding_failure_raises_http_500(isolated_store) -> None:
    from fastapi import HTTPException

    service = RAGService()
    db = MagicMock()

    with patch(
        "src.services.rag.generate_embedding", side_effect=RuntimeError("ollama down")
    ):
        with pytest.raises(HTTPException) as exc:
            service._retrieve_and_build_messages("q", db, None)

    assert exc.value.status_code == 500


def test_answer_question_stores_turn(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [_vector_record("c1", "ctx", 0.9, "a.pdf")]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
        patch("src.services.rag.generate_chat_response", return_value="the answer"),
    ):
        sid, answer, sources = service.answer_question("q", db, None)

    assert answer == "the answer"
    assert isolated_store.get_history(sid) == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "the answer"},
    ]


def test_stream_answer_stores_full_answer_after_exhaustion(isolated_store) -> None:
    service = RAGService()
    db = MagicMock()
    db.run.return_value = [_vector_record("c1", "ctx", 0.9, "a.pdf")]

    with (
        patch("src.services.rag.generate_embedding", return_value=[0.1] * 2560),
        patch("src.services.rag.extract_entities", return_value=EMPTY_ENTITIES),
        patch(
            "src.services.rag.generate_chat_stream",
            return_value=iter(["Hel", "lo"]),
        ),
    ):
        sid, sources, token_iter = service.stream_answer("q", db, None)
        # History is only written once the iterator is fully consumed.
        assert isolated_store.get_history(sid) == []
        tokens = list(token_iter)

    assert tokens == ["Hel", "lo"]
    assert isolated_store.get_history(sid) == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "Hello"},
    ]
