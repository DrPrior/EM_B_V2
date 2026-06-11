"""Unit tests for the in-memory conversation store."""

import pytest

from src.services.session import ConversationStore

pytestmark = pytest.mark.unit


def test_get_or_create_makes_new_session_for_none() -> None:
    store = ConversationStore(max_turns=10)

    sid, history = store.get_or_create(None)

    assert isinstance(sid, str) and sid
    assert history == []


def test_get_or_create_returns_existing_session() -> None:
    store = ConversationStore(max_turns=10)
    sid, _ = store.get_or_create(None)
    store.add_turn(sid, "q", "a")

    same_sid, history = store.get_or_create(sid)

    assert same_sid == sid
    assert history == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]


def test_get_or_create_unknown_id_creates_fresh_session() -> None:
    store = ConversationStore(max_turns=10)

    sid, history = store.get_or_create("does-not-exist")

    # A brand-new id is minted rather than reusing the unknown one.
    assert sid != "does-not-exist"
    assert history == []


def test_add_turn_appends_user_and_assistant_messages() -> None:
    store = ConversationStore(max_turns=10)
    sid, _ = store.get_or_create(None)

    store.add_turn(sid, "hello", "hi there")

    history = store.get_history(sid)
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_history_capped_at_max_turns() -> None:
    store = ConversationStore(max_turns=2)  # keeps 4 messages
    sid, _ = store.get_or_create(None)

    for i in range(5):
        store.add_turn(sid, f"q{i}", f"a{i}")

    history = store.get_history(sid)
    assert len(history) == 4  # 2 turns * 2 messages
    # Oldest turns evicted; the two most recent turns survive.
    assert history[0] == {"role": "user", "content": "q3"}
    assert history[-1] == {"role": "assistant", "content": "a4"}


def test_add_turn_to_unknown_session_is_noop() -> None:
    store = ConversationStore(max_turns=10)

    store.add_turn("ghost", "q", "a")  # must not raise

    assert store.get_history("ghost") is None


def test_get_history_unknown_session_returns_none() -> None:
    store = ConversationStore(max_turns=10)

    assert store.get_history("nope") is None


def test_delete_session_returns_true_then_false() -> None:
    store = ConversationStore(max_turns=10)
    sid, _ = store.get_or_create(None)

    assert store.delete_session(sid) is True
    assert store.delete_session(sid) is False
    assert store.get_history(sid) is None
