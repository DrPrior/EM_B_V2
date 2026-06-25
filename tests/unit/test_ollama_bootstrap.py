"""Unit tests for the host-native Ollama startup bootstrap (HTTP mocked)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services import ollama_bootstrap
from src.services.ollama_bootstrap import (
    OllamaUnavailableError,
    ensure_models,
    wait_for_ollama,
)

pytestmark = pytest.mark.unit


def _ok_post() -> MagicMock:
    """A POST response whose raise_for_status is a no-op."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    return resp


def test_wait_for_ollama_succeeds_on_first_try() -> None:
    resp = MagicMock()
    resp.json.return_value = {"version": "0.1.0"}
    resp.raise_for_status.return_value = None

    with patch.object(ollama_bootstrap.requests, "get", return_value=resp) as get:
        wait_for_ollama()  # should not raise

    get.assert_called_once()


def test_wait_for_ollama_retries_then_fails_fast() -> None:
    # Every heartbeat refuses the connection.
    with (
        patch.object(
            ollama_bootstrap.requests,
            "get",
            side_effect=requests.ConnectionError("refused"),
        ) as get,
        patch("time.sleep") as sleep,  # don't actually wait between retries
    ):
        with pytest.raises(OllamaUnavailableError):
            wait_for_ollama()

    # One GET per allowed attempt; sleeps between them (one fewer than attempts).
    assert get.call_count == ollama_bootstrap.settings.ollama_startup_retries
    assert sleep.call_count == ollama_bootstrap.settings.ollama_startup_retries - 1


def test_ensure_models_skips_when_variants_present() -> None:
    tags_resp = MagicMock()
    tags_resp.raise_for_status.return_value = None
    tags_resp.json.return_value = {
        "models": [
            {"name": f"{ollama_bootstrap.settings.chat_model}:latest"},
            {"name": f"{ollama_bootstrap.settings.embedding_model}:latest"},
        ]
    }

    with (
        patch.object(ollama_bootstrap.requests, "get", return_value=tags_resp),
        patch.object(ollama_bootstrap.requests, "post") as post,
    ):
        ensure_models()

    # Nothing to pull or create — no write calls at all.
    post.assert_not_called()


def test_ensure_models_pulls_and_creates_when_absent() -> None:
    tags_resp = MagicMock()
    tags_resp.raise_for_status.return_value = None
    tags_resp.json.return_value = {"models": []}  # cold host

    with (
        patch.object(ollama_bootstrap.requests, "get", return_value=tags_resp),
        patch.object(
            ollama_bootstrap.requests, "post", return_value=_ok_post()
        ) as post,
        # Don't depend on the real Modelfiles being on disk during the test.
        patch.object(ollama_bootstrap.Path, "is_file", return_value=True),
        patch.object(ollama_bootstrap.Path, "read_text", return_value="FROM base\n"),
    ):
        ensure_models()

    # Two variants, each missing: pull base + create variant = 4 POSTs.
    assert post.call_count == 4
    called_urls = [c.args[0] for c in post.call_args_list]
    assert sum("/api/pull" in u for u in called_urls) == 2
    assert sum("/api/create" in u for u in called_urls) == 2

    # The create calls use Ollama's modern structured schema (model + from),
    # not the deprecated raw-modelfile string field.
    create_bodies = [
        c.kwargs["json"] for c in post.call_args_list if "/api/create" in c.args[0]
    ]
    for body in create_bodies:
        assert "model" in body and "from" in body
        assert "modelfile" not in body


def test_parse_modelfile_extracts_system_and_typed_parameters() -> None:
    modelfile = (
        "FROM gemma4:12b-it-qat\n"
        "# a comment\n"
        "PARAMETER temperature 0\n"
        "PARAMETER top_p 0.9\n"
        "PARAMETER num_ctx 8192\n"
        '\nSYSTEM """Answer only from the graph.\nBe concise."""\n'
    )
    system, params = ollama_bootstrap._parse_modelfile(modelfile)

    assert system == "Answer only from the graph.\nBe concise."
    assert params["temperature"] == 0  # int
    assert params["top_p"] == 0.9  # float
    assert params["num_ctx"] == 8192
    # FROM is intentionally not surfaced as a parameter.
    assert "FROM" not in params and "from" not in params


def test_parse_modelfile_handles_single_line_triple_quoted_system() -> None:
    system, params = ollama_bootstrap._parse_modelfile('SYSTEM """one line"""\n')
    assert system == "one line"
    assert params == {}
