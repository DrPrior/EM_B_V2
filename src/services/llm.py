import json
from collections.abc import Iterator

import requests

from src.core.config import settings


def generate_response(prompt: str) -> str:
    """Sends a raw text prompt to the chat model and returns the generated text."""
    url = f"{settings.ollama_base_url}/api/generate"
    payload = {
        "model": settings.chat_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 8192},
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json().get("response", "")


def generate_chat_response(messages: list[dict]) -> str:
    """Sends a role-based message list to the chat model and returns the reply.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str} dicts.

    Returns:
        The model's reply text.
    """
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.chat_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 8192},
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "")


def generate_chat_stream(messages: list[dict]) -> Iterator[str]:
    """Streams token strings from the chat model one at a time.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str} dicts.

    Yields:
        Individual token strings as the model generates them.
    """
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.chat_model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.3, "num_ctx": 8192},
    }
    with requests.post(url, json=payload, stream=True) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield token
            if chunk.get("done"):
                break
