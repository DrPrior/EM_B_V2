"""Unit tests for the LLM service (Ollama mocked)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services.llm import (
    generate_chat_response,
    generate_chat_stream,
    generate_response,
)

pytestmark = pytest.mark.unit


def test_generate_response_returns_text() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "an answer"}
    mock_response.raise_for_status.return_value = None

    with patch("src.services.llm.requests.post", return_value=mock_response) as p:
        result = generate_response("a prompt")

    assert result == "an answer"
    _, kwargs = p.call_args
    assert kwargs["json"]["prompt"] == "a prompt"
    assert kwargs["json"]["stream"] is False


def test_generate_response_propagates_http_error() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("boom")

    with patch("src.services.llm.requests.post", return_value=mock_response):
        with pytest.raises(requests.HTTPError):
            generate_response("p")


def test_generate_chat_response_extracts_message_content() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": "hello"}}
    mock_response.raise_for_status.return_value = None
    messages = [{"role": "user", "content": "hi"}]

    with patch("src.services.llm.requests.post", return_value=mock_response) as p:
        result = generate_chat_response(messages)

    assert result == "hello"
    _, kwargs = p.call_args
    assert kwargs["json"]["messages"] == messages


def test_generate_chat_response_missing_content_returns_empty() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status.return_value = None

    with patch("src.services.llm.requests.post", return_value=mock_response):
        assert generate_chat_response([]) == ""


def test_generate_chat_stream_yields_tokens_until_done() -> None:
    lines = [
        b'{"message": {"content": "Hel"}, "done": false}',
        b"",  # blank lines are skipped
        b'{"message": {"content": "lo"}, "done": false}',
        b'{"message": {"content": "!"}, "done": true}',
        b'{"message": {"content": "ignored"}, "done": false}',
    ]
    mock_response = MagicMock()
    mock_response.iter_lines.return_value = iter(lines)
    mock_response.raise_for_status.return_value = None
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False

    with patch("src.services.llm.requests.post", return_value=mock_response):
        tokens = list(generate_chat_stream([{"role": "user", "content": "hi"}]))

    # Stops at the done=true chunk; the trailing chunk is never yielded.
    assert tokens == ["Hel", "lo", "!"]
