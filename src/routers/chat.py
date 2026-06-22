import json
from collections.abc import Generator, Iterator

from fastapi import (  # type: ignore[import-untyped]
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import StreamingResponse  # type: ignore[import-untyped]
from neo4j import READ_ACCESS, Session  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.rate_limit import chat_rate_limit, limiter
from src.database.connection import Neo4jConnection
from src.services.rag import RAGService
from src.services.session import Message, conversation_store

router = APIRouter(prefix="/chat", tags=["chat"])
rag_service = RAGService()


class ChatRequest(BaseModel):
    question: str = Field(..., description="The user's question.")
    session_id: str | None = Field(
        default=None,
        description="Session UUID from a prior response. Omit to start a new session.",
    )

    @field_validator("question")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question cannot be empty")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What is emergency management?",
                "session_id": None,
            }
        }
    )


class Source(BaseModel):
    filename: str = Field(..., description="Source document filename.")
    score: float = Field(..., description="Cosine similarity score (0-1).")
    superseded_by: str | None = Field(
        default=None,
        description=(
            "Title of the current document that supersedes this source, if any. "
            "Superseded sources are still returned (historical reference)."
        ),
    )


class ChatResponse(BaseModel):
    answer: str = Field(..., description="The LLM-generated answer.")
    session_id: str = Field(
        ..., description="Session UUID — pass this in follow-up questions."
    )
    sources: list[Source] = Field(
        default_factory=list,
        description="Documents used to generate the answer.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "Emergency management is...",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "sources": [{"filename": "FEMA_Guide.pdf", "score": 0.91}],
            }
        }
    )


class HistoryResponse(BaseModel):
    session_id: str
    history: list[Message]


def get_db_session() -> Generator[Session, None, None]:
    # Chat retrieval is read-only — a READ session makes the server reject any
    # accidental write (the closest equivalent to a read-only DB user, which
    # Neo4j Community Edition cannot provide).
    connection = Neo4jConnection.get_instance()
    yield from connection.get_session_dependency(access_mode=READ_ACCESS)


@router.post("/", response_model=ChatResponse)
@limiter.limit(chat_rate_limit)
def chat_with_graph(
    request: Request,
    payload: ChatRequest,
    session: Session = Depends(get_db_session),
) -> ChatResponse:
    """Answer a question using RAG.

    Pass the returned session_id to maintain conversation context.
    """
    try:
        session_id, answer, sources = rag_service.answer_question(
            payload.question, session, payload.session_id
        )
        return ChatResponse(
            answer=answer,
            session_id=session_id,
            sources=[
                Source(
                    filename=s["filename"],
                    score=s["score"],
                    superseded_by=s.get("superseded_by"),
                )
                for s in sources
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat request: {str(e)}",
        ) from e


@router.post("/stream")
@limiter.limit(chat_rate_limit)
def chat_stream(
    request: Request,
    payload: ChatRequest,
    session: Session = Depends(get_db_session),
) -> StreamingResponse:
    """Answer a question with a streaming SSE response.

    Emits three event types:
    - ``metadata`` — first event, carries session_id and sources list
    - ``token``    — one per generated token
    - ``done``     — final event signalling stream completion
    - ``error``    — emitted if LLM streaming fails mid-response
    """
    try:
        sid, sources, token_iter = rag_service.stream_answer(
            payload.question, session, payload.session_id
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare stream: {str(e)}",
        ) from e

    def event_stream() -> Iterator[str]:
        metadata = {"type": "metadata", "session_id": sid, "sources": sources}
        yield f"data: {json.dumps(metadata)}\n\n"
        try:
            for token in token_iter:
                yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/history", response_model=HistoryResponse)
def get_session_history(session_id: str) -> HistoryResponse:
    """Return the full conversation history for a session."""
    history = conversation_store.get_history(session_id)
    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return HistoryResponse(session_id=session_id, history=history)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str) -> None:
    """Clear a conversation session."""
    if not conversation_store.delete_session(session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
