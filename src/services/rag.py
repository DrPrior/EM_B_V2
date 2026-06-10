from collections.abc import Iterator
from typing import cast

from fastapi import HTTPException, status  # type: ignore[import-untyped]
from neo4j import Session  # type: ignore[import-untyped]

from pipeline.extract import extract_entities
from src.core.config import settings
from src.services.embeddings import generate_embedding
from src.services.llm import generate_chat_response, generate_chat_stream
from src.services.session import conversation_store

_SYSTEM_PROMPT = (
    "You answer questions based on official documents, training manuals, "
    "policies, and legal references in the knowledge base.\n\n"
    "When answering:\n"
    "- Base your answers strictly on the provided context\n"
    "- If the context does not contain enough information, say so clearly\n"
    "- Cite source documents inline using the format (Source: filename), "
    "e.g. (Source: FEMA_Guide.pdf)\n"
    "- When multiple sources support the same point, synthesize them into a "
    "single statement and cite all sources used\n"
    "- Be concise and accurate"
)

_VECTOR_QUERY = """
CALL db.index.vector.queryNodes('chunk_vector_idx', $top_k, $embedding)
YIELD node, score
OPTIONAL MATCH (doc:Document)-[:HAS_CHUNK]->(node)
RETURN node.chunk_id AS chunk_id, node.text AS text, score,
       coalesce(doc.filename, 'Unknown') AS filename
"""

_GRAPH_QUERY = """
MATCH (chunk:Chunk)
WHERE chunk.embedding IS NOT NULL
AND (
  (size($entity_names) > 0 AND EXISTS {
    MATCH (chunk)-[:MENTIONS]->(e)
    WHERE (e:Concept OR e:Organization)
    AND any(name IN $entity_names WHERE toLower(e.name) = toLower(name))
  })
  OR
  (size($legal_names) > 0 AND EXISTS {
    MATCH (chunk)-[:CITES]->(l:LegalReference)
    WHERE any(name IN $legal_names WHERE toLower(l.name) = toLower(name))
  })
)
WITH chunk, vector.similarity.cosine(chunk.embedding, $embedding) AS score
WHERE score >= $min_score
OPTIONAL MATCH (doc:Document)-[:HAS_CHUNK]->(chunk)
RETURN DISTINCT chunk.chunk_id AS chunk_id, chunk.text AS text,
       coalesce(doc.filename, 'Unknown') AS filename, score
ORDER BY score DESC
LIMIT $limit
"""


class RAGService:
    """Retrieval-Augmented Generation pipeline with vector + graph-augmented retrieval."""

    def _retrieve_and_build_messages(
        self,
        question: str,
        db_session: Session,
        session_id: str | None,
    ) -> tuple[str, list[dict], list[dict]]:
        """Run hybrid retrieval and build the LLM message list.

        Returns:
            (sid, messages, sources) where sources is a list of
            {"filename": str, "score": float} dicts.
        """
        sid, history = conversation_store.get_or_create(session_id)

        try:
            question_vector = generate_embedding(question)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate embeddings: {str(e)}",
            )

        vector_records = list(
            db_session.run(_VECTOR_QUERY, embedding=question_vector, top_k=settings.retrieval_top_k)
        )

        graph_records: list = []
        try:
            entities = extract_entities(question)
            entity_names = [c for c in entities["concepts"]] + [
                o["name"] for o in entities["organizations"]
            ]
            legal_names = entities["legal_references"]

            if entity_names or legal_names:
                graph_records = list(
                    db_session.run(
                        _GRAPH_QUERY,
                        entity_names=entity_names,
                        legal_names=legal_names,
                        embedding=question_vector,
                        min_score=settings.graph_retrieval_min_score,
                        limit=settings.graph_retrieval_limit,
                    )
                )
        except Exception:
            pass  # graph traversal is additive — degrade gracefully to vector-only

        seen_ids: set[str] = set()
        seen_texts: set[str] = set()
        merged: list[dict] = []

        for r in vector_records:
            if r["score"] < settings.vector_retrieval_min_score:
                continue
            cid = r["chunk_id"]
            text_key = r["text"][:200]
            if cid not in seen_ids and text_key not in seen_texts:
                seen_ids.add(cid)
                seen_texts.add(text_key)
                merged.append({
                    "chunk_id": cid,
                    "text": r["text"],
                    "filename": r["filename"],
                    "score": round(r["score"], 4),
                })

        for r in graph_records:
            cid = r["chunk_id"]
            text_key = r["text"][:200]
            if cid not in seen_ids and text_key not in seen_texts:
                seen_ids.add(cid)
                seen_texts.add(text_key)
                merged.append({
                    "chunk_id": cid,
                    "text": r["text"],
                    "filename": r["filename"],
                    "score": round(r["score"], 4),
                })

        sources = [{"filename": r["filename"], "score": r["score"]} for r in merged]

        if merged:
            context_parts = [f"[Source: {r['filename']}]\n{r['text']}" for r in merged]
            context = "\n\n".join(context_parts)
            user_content = f"Context:\n{context}\n\nQuestion: {question}"
        else:
            user_content = (
                f"Question: {question}\n\n"
                "(No relevant context was found in the knowledge base. "
                "Answer based on the conversation history if applicable, "
                "otherwise state that you don't have enough information.)"
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        messages.extend(cast(list[dict[str, str]], history))
        messages.append({"role": "user", "content": user_content})

        return sid, messages, sources

    def answer_question(
        self,
        question: str,
        db_session: Session,
        session_id: str | None = None,
    ) -> tuple[str, str, list[dict]]:
        """Generate a complete answer (non-streaming).

        Returns:
            Tuple of (session_id, answer, sources).
        """
        sid, messages, sources = self._retrieve_and_build_messages(
            question, db_session, session_id
        )

        try:
            answer = generate_chat_response(messages)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate response: {str(e)}",
            )

        conversation_store.add_turn(sid, question, answer)
        return sid, answer, sources

    def stream_answer(
        self,
        question: str,
        db_session: Session,
        session_id: str | None = None,
    ) -> tuple[str, list[dict], Iterator[str]]:
        """Generate a streaming answer.

        Runs retrieval synchronously, then returns a token iterator. The full
        answer is accumulated inside the iterator and stored in session history
        when the iterator is exhausted.

        Returns:
            Tuple of (session_id, sources, token_iterator).
        """
        sid, messages, sources = self._retrieve_and_build_messages(
            question, db_session, session_id
        )

        def _token_gen() -> Iterator[str]:
            tokens: list[str] = []
            try:
                for token in generate_chat_stream(messages):
                    tokens.append(token)
                    yield token
            finally:
                # Store the turn whether the client disconnects early or not
                conversation_store.add_turn(sid, question, "".join(tokens))

        return sid, sources, _token_gen()
