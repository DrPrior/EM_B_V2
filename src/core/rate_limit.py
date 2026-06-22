"""Per-IP rate limiting for the API.

A single shared ``Limiter`` instance is registered on the FastAPI app in
``src.main`` and applied to chat endpoints via the ``@limiter.limit`` decorator.
Keying on the client's remote address caps how many requests one IP can make
per minute, protecting the API and the LLM inference budget.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.config import settings

limiter = Limiter(key_func=get_remote_address)


def chat_rate_limit() -> str:
    """Return the per-IP chat limit as a slowapi limit string.

    Evaluated per request (not at import time) so the limit reflects the current
    ``settings.rate_limit_per_minute`` value — which also lets tests tune it.
    """
    return f"{settings.rate_limit_per_minute}/minute"
