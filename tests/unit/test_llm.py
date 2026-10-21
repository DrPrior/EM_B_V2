"""Unit tests for the LLM service (Ollama mocked)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services.llm import (
    OllamaError,
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
    # Thinking must be disabled: chat-model (gemma4) otherwise spends the
    # num_predict budget on a `thinking` channel and returns empty output.
    assert kwargs["json"]["think"] is False


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
    # Reasoning off so `message.content` is populated (not left empty while the
    # budget is spent in `message.thinking`).
    assert kwargs["json"]["think"] is False


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

    with patch("src.services.llm.requests.post", return_value=mock_response) as p:
        tokens = list(generate_chat_stream([{"role": "user", "content": "hi"}]))

    # Stops at the done=true chunk; the trailing chunk is never yielded.
    assert tokens == ["Hel", "lo", "!"]
    # Reasoning off so streamed `message.content` tokens actually arrive.
    _, kwargs = p.call_args
    assert kwargs["json"]["think"] is False


def _ollama_500(body: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.HTTPError(
        "500 Server Error: Internal Server Error for url: http://localhost:11434"
    )
    mock_response.json.return_value = body
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    return mock_response


def test_http_error_carries_ollama_error_message() -> None:
    mock_response = _ollama_500({"error": "llama runner process has terminated"})

    with patch("src.services.llm.requests.post", return_value=mock_response):
        with pytest.raises(requests.HTTPError) as excinfo:
            generate_chat_response([])

    assert "500 Server Error" in str(excinfo.value)
    assert "llama runner process has terminated" in str(excinfo.value)


def test_http_error_falls_back_to_body_text_when_not_json() -> None:
    mock_response = _ollama_500({})
    mock_response.json.side_effect = ValueError("not json")
    mock_response.text = "upstream gone"

    with patch("src.services.llm.requests.post", return_value=mock_response):
        with pytest.raises(requests.HTTPError, match="upstream gone"):
            generate_response("p")


def test_generate_chat_stream_raises_on_http_error_with_detail() -> None:
    mock_response = _ollama_500({"error": "device lost"})

    with patch("src.services.llm.requests.post", return_value=mock_response):
        with pytest.raises(requests.HTTPError, match="device lost"):
            list(generate_chat_stream([]))


def _stream(lines: list[bytes]) -> MagicMock:
    mock_response = MagicMock()
    mock_response.iter_lines.return_value = iter(lines)
    mock_response.raise_for_status.return_value = None
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    return mock_response


def test_generate_chat_stream_raises_on_in_stream_error() -> None:
    # Ollama has already sent 200, so a runner failure arrives as an error line.
    lines = [
        b'{"message": {"content": "Haz"}, "done": false}',
        b'{"error": "llama runner process has terminated"}',
    ]

    with patch("src.services.llm.requests.post", return_value=_stream(lines)):
        stream = generate_chat_stream([])
        assert next(stream) == "Haz"
        with pytest.raises(OllamaError, match="llama runner process has terminated"):
            next(stream)


def test_generate_chat_stream_raises_when_stream_ends_without_done() -> None:
    lines = [b'{"message": {"content": "Haz"}, "done": false}']

    with patch("src.services.llm.requests.post", return_value=_stream(lines)):
        with pytest.raises(OllamaError, match="ended before"):
            list(generate_chat_stream([]))
