import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import TypedDict

from src.core.config import settings


class Message(TypedDict):
    role: str
    content: str


class _SessionData:
    def __init__(self, max_messages: int) -> None:
        self.history: deque[Message] = deque(maxlen=max_messages)
        self.created_at: datetime = datetime.now(UTC)
        self.last_active: datetime = datetime.now(UTC)


class ConversationStore:
    """Thread-safe in-memory store for conversation history, keyed by session UUID."""

    def __init__(self, max_turns: int = 10) -> None:
        self._max_messages = max_turns * 2  # each turn = 1 user + 1 assistant message
        self._sessions: dict[str, _SessionData] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str | None) -> tuple[str, list[Message]]:
        """Return (session_id, history).

        Creates a new session if id is None or unknown.
        """
        with self._lock:
            if not session_id or session_id not in self._sessions:
                session_id = str(uuid.uuid4())
                self._sessions[session_id] = _SessionData(self._max_messages)
            session = self._sessions[session_id]
            session.last_active = datetime.now(UTC)
            return session_id, list(session.history)

    def add_turn(self, session_id: str, question: str, answer: str) -> None:
        """Append a user/assistant turn to the session history."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.history.append({"role": "user", "content": question})
                session.history.append({"role": "assistant", "content": answer})
                session.last_active = datetime.now(UTC)

    def get_history(self, session_id: str) -> list[Message] | None:
        """Return history for a session, or None if the session does not exist."""
        with self._lock:
            session = self._sessions.get(session_id)
            return list(session.history) if session is not None else None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None


conversation_store = ConversationStore(max_turns=settings.max_history_turns)
