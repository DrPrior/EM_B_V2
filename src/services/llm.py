import json
from collections.abc import Iterator

import requests

from src.core.config import settings
from src.core.timing import log_ollama, parse_ollama_timings


class OllamaError(RuntimeError):
    """Ollama failed partway through a streamed response.

    Ollama has already answered 200 by then, so the failure arrives as an
    ``error`` field in the stream, or as the stream ending with no ``done``
    chunk (the runner process died).
    """


def raise_for_ollama(response: requests.Response) -> None:
    """Like ``raise_for_status``, but keeps Ollama's own error message.

    ``raise_for_status`` reports only the status line ("500 Server Error ...");
    the reason (e.g. the model runner crashing) is in the JSON body's ``error``
    field, and without it the logs can't say why a call failed.
    """
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        try:
            detail = response.json().get("error") or response.text
        except ValueError:
            detail = response.text
        raise requests.HTTPError(
            f"{e} (Ollama: {str(detail)[:500]})", response=response
        ) from e


def generate_response(
    prompt: str,
    session_id: str | None = None,
    num_predict: int | None = None,
    format_json: bool = False,
) -> str:
    """Sends a raw text prompt to the chat model and returns the generated text.

    Args:
        prompt: The raw text prompt.
        session_id: Conversation id used to correlate timing logs across stages.
        num_predict: Cap on tokens generated. ``None`` leaves it unbounded.
        format_json: When true, constrains output to valid JSON (Ollama's
            ``format: json`` mode) so the model stops as soon as the object is
            complete instead of padding with prose/markdown.

    Returns:
        The generated text.
    """
    url = f"{settings.ollama_base_url}/api/generate"
    options: dict = {"temperature": 0.3, "num_ctx": settings.chat_num_ctx}
    if num_predict is not None:
        options["num_predict"] = num_predict
    payload: dict = {
        "model": settings.chat_model,
        "prompt": prompt,
        "stream": False,
        # chat-model (gemma4) is a reasoning model: left on, it emits its
        # chain-of-thought into a separate `thinking` channel and can consume the
        # entire num_predict budget before producing any real output. We never use
        # the reasoning tokens, so disable thinking — this keeps `response`
        # populated and cuts latency.
        "think": False,
        "options": options,
    }
    if format_json:
        payload["format"] = "json"
    response = requests.post(url, json=payload)
    raise_for_ollama(response)
    body = response.json()
    log_ollama("generate", settings.chat_model, parse_ollama_timings(body), session_id)
    return body.get("response", "")


def generate_chat_response(messages: list[dict], session_id: str | None = None) -> str:
    """Sends a role-based message list to the chat model and returns the reply.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str} dicts.
        session_id: Conversation id used to correlate timing logs across stages.

    Returns:
        The model's reply text.
    """
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.chat_model,
        "messages": messages,
        "stream": False,
        # Disable the model's reasoning channel: with thinking on, gemma4 spends
        # the num_predict budget on `message.thinking` and returns an empty
        # `message.content` (done_reason=length), which surfaces as a blank answer.
        "think": False,
        "options": {
            "temperature": 0.3,
            "num_ctx": settings.chat_num_ctx,
            "num_predict": settings.answer_max_tokens,
        },
    }
    response = requests.post(url, json=payload)
    raise_for_ollama(response)
    body = response.json()
    log_ollama("chat", settings.chat_model, parse_ollama_timings(body), session_id)
    return body.get("message", {}).get("content", "")


def generate_chat_stream(
    messages: list[dict], session_id: str | None = None
) -> Iterator[str]:
    """Streams token strings from the chat model one at a time.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str} dicts.
        session_id: Conversation id used to correlate timing logs across stages.

    Yields:
        Individual token strings as the model generates them.

    Raises:
        requests.HTTPError: Ollama rejected the request outright.
        OllamaError: Ollama failed after the stream had started.
    """
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.chat_model,
        "messages": messages,
        "stream": True,
        # See generate_chat_response: thinking must be off or the streamed
        # `message.content` tokens never arrive (they go to `thinking`), leaving
        # the UI with no visible response.
        "think": False,
        "options": {
            "temperature": 0.3,
            "num_ctx": settings.chat_num_ctx,
            "num_predict": settings.answer_max_tokens,
        },
    }
    with requests.post(url, json=payload, stream=True) as response:
        raise_for_ollama(response)
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if "error" in chunk:
                raise OllamaError(f"Ollama chat stream failed: {chunk['error']}")
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield token
            if chunk.get("done"):
                # The final chunk carries the call's internal timing fields.
                log_ollama(
                    "chat", settings.chat_model, parse_ollama_timings(chunk), session_id
                )
                break
        else:
            raise OllamaError("Ollama chat stream ended before the response completed")
