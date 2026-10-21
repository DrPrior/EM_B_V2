"""Central logging configuration for the API.

Every application logger lives under the ``em_b`` namespace (``em_b.rag``,
``em_b.timing``, ``em_b.bootstrap`` …) and propagates up to a single handler that
:func:`configure_logging` installs on the ``em_b`` logger. Modules only ever call
``logging.getLogger("em_b.<area>")`` — they never attach handlers themselves.

Exactly one main destination is chosen:

- **File mode** — when ``LOG_DIR`` is set, or the app is running frozen
  (PyInstaller). Records go to a size-capped rotating ``api.log`` and nothing is
  written to the console. uvicorn's own loggers are rerouted into the same file,
  because ``uvicorn.run`` installs console handlers before the lifespan runs. The
  Electron shell sets ``LOG_DIR`` when it spawns the API.
- **Console mode** — otherwise (``scripts/dev-up.ps1``, ``uvicorn --reload``,
  ``python -m pipeline.*``). Records go to stdout, as before.

Console mode also keeps a **dev error log** (``DEV_ERROR_LOG``, on by default):
WARNING-and-above records, tracebacks included, are copied to a rotating
``logs/errors.log`` at the repo root. Console output scrolls away when the
terminal is closed or restarted, and that used to take the only record of a
crash with it. uvicorn's ``uvicorn.error`` records (unhandled exceptions) are
copied there too, while uvicorn keeps its own console handlers.

Set ``LOG_DIR`` in dev to exercise file mode without packaging.

Privacy: user question text is only ever logged at DEBUG. INFO and above carry
ids, filenames, scores, counts, and timings — never questions or chunk text — so
a default-level log file is safe to send when reporting a problem.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core import paths
from src.core.config import settings

APP_LOGGER = "em_b"
LOG_FILENAME = "api.log"
ERROR_LOG_FILENAME = "errors.log"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# uvicorn loggers that carry their own handlers ("uvicorn.error" propagates to
# "uvicorn"). File mode reroutes both; console mode only adds the error handler
# to "uvicorn", leaving its console output alone.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")

# Names given to handlers this module installs, so re-configuration (uvicorn
# --reload, tests) replaces them instead of stacking duplicates.
_HANDLER_NAME = "em_b-handler"
_ERROR_HANDLER_NAME = "em_b-error-handler"


def resolve_log_dir() -> Path | None:
    """Return the directory to write log files into, or None for console mode.

    ``settings.log_dir`` (``LOG_DIR``) wins; a frozen build with no explicit
    directory falls back to :func:`src.core.paths.default_log_dir`.
    """
    if settings.log_dir:
        return Path(settings.log_dir)
    return paths.default_log_dir()


def _rotating_file_handler(path: Path, delay: bool = False) -> RotatingFileHandler:
    """A size-capped rotating file handler, creating its directory first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return RotatingFileHandler(
        path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
        delay=delay,
    )


def _build_handler(log_dir: Path | None) -> logging.Handler:
    """Create the single handler for the chosen destination."""
    handler: logging.Handler
    if log_dir is None:
        handler = logging.StreamHandler(sys.stdout)
    else:
        handler = _rotating_file_handler(log_dir / LOG_FILENAME)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def _build_error_handler(error_dir: Path) -> logging.Handler:
    """Create the WARNING+ dev error-log handler.

    ``delay=True`` means ``errors.log`` is only created once something worth
    recording happens, so an empty file never suggests a problem.
    """
    handler = _rotating_file_handler(error_dir / ERROR_LOG_FILENAME, delay=True)
    handler.set_name(_ERROR_HANDLER_NAME)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def _replace_handlers(logger: logging.Logger, *handlers: logging.Handler) -> None:
    """Swap every handler on ``logger`` for ``handlers``, closing our old ones."""
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        if (
            existing.get_name() in (_HANDLER_NAME, _ERROR_HANDLER_NAME)
            and existing not in handlers
        ):
            existing.close()
    for handler in handlers:
        logger.addHandler(handler)


def _set_error_handler(logger: logging.Logger, handler: logging.Handler | None) -> None:
    """Install ``handler`` as ``logger``'s dev error handler, or remove it if None.

    Unlike :func:`_replace_handlers`, handlers installed by someone else (uvicorn's
    console handlers) are left in place.
    """
    for existing in list(logger.handlers):
        if existing.get_name() == _ERROR_HANDLER_NAME and existing is not handler:
            logger.removeHandler(existing)
            existing.close()
    if handler is not None and handler not in logger.handlers:
        logger.addHandler(handler)


def configure_logging() -> Path | None:
    """Install the application log handlers. Safe to call more than once.

    Returns:
        The log directory in file mode, or None in console mode.
    """
    log_dir = resolve_log_dir()
    handler = _build_handler(log_dir)
    error_handler = (
        _build_error_handler(paths.dev_error_log_dir())
        if log_dir is None and settings.dev_error_log
        else None
    )

    app_logger = logging.getLogger(APP_LOGGER)
    if error_handler is None:
        _replace_handlers(app_logger, handler)
    else:
        _replace_handlers(app_logger, handler, error_handler)
    app_logger.setLevel(settings.log_level.upper())
    # Don't also hand records to the root logger — keeps output single-copy
    # whatever the host process has configured on root.
    app_logger.propagate = False

    if log_dir is not None:
        for name in _UVICORN_LOGGERS:
            _replace_handlers(logging.getLogger(name), handler)
    else:
        _set_error_handler(logging.getLogger("uvicorn"), error_handler)

    return log_dir
