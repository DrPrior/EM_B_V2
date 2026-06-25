"""Startup bootstrap for the host-native (hybrid) Ollama daemon.

In the hybrid deployment Ollama no longer runs as a Docker service — it runs
natively on each host so it can use the host GPU (Metal / CUDA / Vulkan). That
means the work the old ``ollama-startup.sh`` entrypoint did inside the Ollama
container (pull the base models, build the custom ``chat-model`` /
``embedding-model`` variants from the Modelfiles) now has to be driven by the
application over HTTP against ``settings.ollama_base_url``
(``http://host.docker.internal:11434`` from inside the container).

This module replays that logic over the Ollama REST API, all idempotent:

- :func:`wait_for_ollama` retries the daemon's ``/api/version`` heartbeat and
  raises (fail-fast) if the host hasn't started Ollama.
- :func:`ensure_models` pulls each base model and builds each custom variant
  only if it is not already present, so the warm path is a single ``/api/tags``
  read.

:func:`bootstrap` chains the two and is called from the FastAPI ``lifespan``.
"""

import logging
import sys
from pathlib import Path

import requests

from src.core.config import settings

logger = logging.getLogger("em_b.bootstrap")

if not logger.handlers and not logging.getLogger().handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False
logger.setLevel(logging.INFO)

# Repo root inside the container is /app (this file is /app/src/services/...).
# The Modelfiles are copied/mounted there; locally this resolves to the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# (variant name, Modelfile path, base model the variant is built FROM).
# Aligned with the FROM lines in Modelfile / Modelfile.embeddings.
_VARIANTS: tuple[tuple[str, Path, str], ...] = (
    (settings.chat_model, _PROJECT_ROOT / "Modelfile", settings.chat_base_model),
    (
        settings.embedding_model,
        _PROJECT_ROOT / "Modelfile.embeddings",
        settings.embedding_base_model,
    ),
)


class OllamaUnavailableError(RuntimeError):
    """Raised when the host Ollama daemon cannot be reached or provisioned."""


def wait_for_ollama() -> None:
    """Block until the host Ollama daemon answers, or fail fast.

    Pings ``GET {ollama_base_url}/api/version`` up to
    ``settings.ollama_startup_retries`` times, sleeping
    ``settings.ollama_startup_delay`` seconds between attempts. This absorbs the
    common race where the API container boots a moment before the user has
    launched Ollama on the host.

    Raises:
        OllamaUnavailableError: If the daemon is still unreachable after all
            retries (the lifespan re-raises this so the container exits with a
            clear message rather than serving broken chat).
    """
    import time

    url = f"{settings.ollama_base_url}/api/version"
    last_exc: Exception | None = None
    logger.info("Connecting to host Ollama daemon at %s ...", settings.ollama_base_url)
    for attempt in range(1, settings.ollama_startup_retries + 1):
        try:
            resp = requests.get(url, timeout=settings.ollama_request_timeout)
            resp.raise_for_status()
            version = resp.json().get("version", "unknown")
            logger.info("Connected to host Ollama (version %s).", version)
            return
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "Host Ollama not responding (attempt %d/%d). Retrying in %.0fs ...",
                attempt,
                settings.ollama_startup_retries,
                settings.ollama_startup_delay,
            )
            if attempt < settings.ollama_startup_retries:
                time.sleep(settings.ollama_startup_delay)

    raise OllamaUnavailableError(
        "CRITICAL: could not reach host Ollama at "
        f"{settings.ollama_base_url}. Start the Ollama application on the host "
        "and ensure OLLAMA_HOST=0.0.0.0 so it accepts traffic from the "
        "container. See docs/HYBRID_SETUP.md."
    ) from last_exc


def _existing_model_tags() -> set[str]:
    """Return the set of model tags currently present on the host daemon."""
    url = f"{settings.ollama_base_url}/api/tags"
    resp = requests.get(url, timeout=settings.ollama_request_timeout)
    resp.raise_for_status()
    return {m.get("name", "") for m in resp.json().get("models", [])}


def _is_present(name: str, tags: set[str]) -> bool:
    """True if ``name`` is among ``tags``.

    Ollama appends ``:latest`` to a name created without an explicit tag (so the
    custom variant ``chat-model`` is listed as ``chat-model:latest``), while base
    models keep their tag (``gemma4:12b-it-qat``). Match either form.
    """
    return name in tags or f"{name}:latest" in tags


def _pull_base(model: str) -> None:
    """Pull a base model onto the host if it isn't already present.

    Uses ``stream: false`` so the call blocks until the (potentially multi-GB)
    download finishes and returns a single final status.
    """
    logger.info("Pulling base model '%s' onto host (this may take a while) ...", model)
    url = f"{settings.ollama_base_url}/api/pull"
    resp = requests.post(
        url,
        json={"model": model, "stream": False},
        timeout=settings.ollama_pull_timeout,
    )
    resp.raise_for_status()
    logger.info("Base model '%s' is present on host.", model)


def _strip_quotes(value: str) -> str:
    """Strip a single pair of surrounding single/double quotes from a value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _coerce_param(value: str) -> object:
    """Coerce a Modelfile PARAMETER value to int/float where possible."""
    value = _strip_quotes(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _parse_modelfile(text: str) -> tuple[str | None, dict[str, object]]:
    """Parse a Modelfile into the structured fields Ollama's /api/create wants.

    Extracts the ``SYSTEM`` block (triple-quoted, possibly multi-line) and any
    ``PARAMETER`` lines into a ``parameters`` dict. ``FROM`` is ignored here —
    the caller supplies the base model explicitly so the model that gets pulled
    and the one the variant is built ``from`` stay in lockstep. Comments and
    blank lines are skipped; repeated parameters accumulate into a list.
    """
    system: str | None = None
    parameters: dict[str, object] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        head, _, rest = stripped.partition(" ")
        keyword = head.upper()
        rest = rest.strip()
        if keyword == "PARAMETER":
            key, _, raw = rest.partition(" ")
            value = _coerce_param(raw.strip())
            if key in parameters:
                existing = parameters[key]
                parameters[key] = (
                    [*existing, value]
                    if isinstance(existing, list)
                    else [existing, value]
                )
            else:
                parameters[key] = value
            i += 1
        elif keyword == "SYSTEM":
            system, i = _read_block(rest, lines, i)
        else:
            # FROM / TEMPLATE / LICENSE / etc. — not needed for create here.
            i += 1
    return system, parameters


def _read_block(rest: str, lines: list[str], i: int) -> tuple[str, int]:
    """Read a directive value that may be a triple-quoted multi-line block.

    Returns the value and the index of the next unconsumed line.
    """
    if rest.startswith('"""'):
        body = rest[3:]
        if body.endswith('"""') and len(body) >= 3:
            return body[:-3], i + 1
        collected = [body]
        j = i + 1
        while j < len(lines):
            if '"""' in lines[j]:
                collected.append(lines[j][: lines[j].index('"""')])
                return "\n".join(collected), j + 1
            collected.append(lines[j])
            j += 1
        return "\n".join(collected), j
    return _strip_quotes(rest), i + 1


def _create_variant(name: str, base: str, modelfile_path: Path) -> None:
    """Build a custom variant on the host from its Modelfile.

    The host daemon cannot read a Modelfile that lives inside this container, and
    Ollama's modern /api/create no longer accepts a raw Modelfile string, so we
    parse the Modelfile and send its SYSTEM/PARAMETER directives as structured
    JSON (the API equivalent of ``ollama create -f``).
    """
    if not modelfile_path.is_file():
        raise OllamaUnavailableError(
            f"Modelfile not found at {modelfile_path}; cannot build variant "
            f"'{name}'. Ensure it is copied into the image / mounted."
        )
    system, parameters = _parse_modelfile(modelfile_path.read_text(encoding="utf-8"))
    payload: dict[str, object] = {"model": name, "from": base, "stream": False}
    if system is not None:
        payload["system"] = system
    if parameters:
        payload["parameters"] = parameters
    logger.info("Creating custom variant '%s' (from %s) ...", name, base)
    url = f"{settings.ollama_base_url}/api/create"
    resp = requests.post(url, json=payload, timeout=settings.ollama_pull_timeout)
    resp.raise_for_status()
    logger.info("Custom variant '%s' built on host.", name)


def ensure_models() -> None:
    """Ensure every base model and custom variant exists on the host daemon.

    Idempotent: reads the current model list once and only pulls/creates what is
    missing, so a warm host returns almost immediately.
    """
    tags = _existing_model_tags()
    for variant, modelfile_path, base in _VARIANTS:
        if _is_present(variant, tags):
            logger.info("Variant '%s' already present — skipping.", variant)
            continue
        if not _is_present(base, tags):
            _pull_base(base)
        _create_variant(variant, base, modelfile_path)


def bootstrap() -> None:
    """Wait for the host Ollama daemon, then provision the required models."""
    wait_for_ollama()
    ensure_models()
