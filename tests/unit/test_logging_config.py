"""Unit tests for the central logging configuration."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from src.core import logging_config
from src.core.config import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _console_defaults(monkeypatch):
    """Start every test from source-mode defaults, whatever the dev's .env says."""
    monkeypatch.setattr(settings, "log_dir", None)
    monkeypatch.setattr(settings, "log_level", "INFO")
    monkeypatch.delattr(sys, "frozen", raising=False)


def _app_handlers() -> list[logging.Handler]:
    return logging.getLogger(logging_config.APP_LOGGER).handlers


def test_console_mode_when_no_log_dir() -> None:
    log_dir = logging_config.configure_logging()

    assert log_dir is None
    handlers = _app_handlers()
    assert len(handlers) == 1
    assert type(handlers[0]) is logging.StreamHandler
    assert handlers[0].stream is sys.stdout


def test_console_mode_leaves_uvicorn_untouched() -> None:
    before = list(logging.getLogger("uvicorn").handlers)

    logging_config.configure_logging()

    assert logging.getLogger("uvicorn").handlers == before


def test_file_mode_writes_rotating_api_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "log_max_bytes", 1234)
    monkeypatch.setattr(settings, "log_backup_count", 3)

    log_dir = logging_config.configure_logging()
    logging.getLogger("em_b.rag").info("hello %s", "file")

    assert log_dir == tmp_path / "logs"
    (handler,) = _app_handlers()
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 1234
    assert handler.backupCount == 3
    handler.flush()
    content = (tmp_path / "logs" / "api.log").read_text(encoding="utf-8")
    assert "INFO" in content
    assert "em_b.rag  hello file" in content


def test_file_mode_has_no_console_output(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))

    logging_config.configure_logging()
    logging.getLogger("em_b.main").error("only in the file")

    assert "only in the file" not in capsys.readouterr().out
    assert all(type(h) is not logging.StreamHandler for h in _app_handlers())


def test_file_mode_reroutes_uvicorn_into_same_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    logging.getLogger("uvicorn").addHandler(logging.StreamHandler(sys.stdout))

    logging_config.configure_logging()

    (app_handler,) = _app_handlers()
    assert logging.getLogger("uvicorn").handlers == [app_handler]
    assert logging.getLogger("uvicorn.access").handlers == [app_handler]


def test_reconfiguring_does_not_stack_handlers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))

    logging_config.configure_logging()
    logging_config.configure_logging()

    assert len(_app_handlers()) == 1
    assert len(logging.getLogger("uvicorn").handlers) == 1


def test_level_and_propagation(monkeypatch) -> None:
    monkeypatch.setattr(settings, "log_level", "debug")

    logging_config.configure_logging()

    app_logger = logging.getLogger(logging_config.APP_LOGGER)
    assert app_logger.level == logging.DEBUG
    assert app_logger.propagate is False


def test_frozen_without_log_dir_uses_logs_beside_executable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "emb-api.exe"))

    log_dir = logging_config.configure_logging()

    assert log_dir == tmp_path.resolve() / "logs"
    assert (log_dir / "api.log").exists()


def test_explicit_log_dir_wins_over_frozen_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "emb-api.exe"))
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "chosen"))

    assert logging_config.resolve_log_dir() == tmp_path / "chosen"


@pytest.fixture
def dev_error_log(monkeypatch, tmp_path: Path) -> Path:
    """Turn the dev error log on, pointed at a temp directory."""
    monkeypatch.setattr(settings, "dev_error_log", True)
    monkeypatch.setattr(logging_config.paths, "dev_error_log_dir", lambda: tmp_path)
    return tmp_path / logging_config.ERROR_LOG_FILENAME


def _error_handler(logger_name: str) -> logging.Handler:
    (handler,) = [
        h
        for h in logging.getLogger(logger_name).handlers
        if h.get_name() == logging_config._ERROR_HANDLER_NAME
    ]
    return handler


def test_dev_error_log_records_warnings_with_traceback(
    dev_error_log: Path, capsys
) -> None:
    logging_config.configure_logging()
    logger = logging.getLogger("em_b.chat")
    logger.info("routine")
    try:
        raise RuntimeError("runner crashed")
    except RuntimeError:
        logger.exception("Chat stream failed")

    _error_handler("em_b").flush()
    content = dev_error_log.read_text(encoding="utf-8")
    assert "ERROR    em_b.chat  Chat stream failed" in content
    assert "RuntimeError: runner crashed" in content
    assert "routine" not in content
    # The console still gets everything.
    out = capsys.readouterr().out
    assert "routine" in out
    assert "Chat stream failed" in out


def test_dev_error_log_is_not_created_until_needed(dev_error_log: Path) -> None:
    logging_config.configure_logging()
    logging.getLogger("em_b.main").info("startup ok")

    assert not dev_error_log.exists()


def test_dev_error_log_captures_uvicorn_errors_and_keeps_its_console(
    dev_error_log: Path,
) -> None:
    uvicorn_console = logging.StreamHandler(sys.stdout)
    logging.getLogger("uvicorn").addHandler(uvicorn_console)

    logging_config.configure_logging()
    logging.getLogger("uvicorn.error").error("Exception in ASGI application")

    assert uvicorn_console in logging.getLogger("uvicorn").handlers
    assert _error_handler("uvicorn") is _error_handler("em_b")
    _error_handler("uvicorn").flush()
    assert "Exception in ASGI application" in dev_error_log.read_text(encoding="utf-8")


def test_dev_error_log_reconfiguring_does_not_stack(dev_error_log: Path) -> None:
    logging_config.configure_logging()
    logging_config.configure_logging()

    assert len(_app_handlers()) == 2
    names = [h.get_name() for h in logging.getLogger("uvicorn").handlers]
    assert names.count(logging_config._ERROR_HANDLER_NAME) == 1


def test_dev_error_log_off_removes_it(monkeypatch, dev_error_log: Path) -> None:
    logging_config.configure_logging()
    monkeypatch.setattr(settings, "dev_error_log", False)

    logging_config.configure_logging()

    assert len(_app_handlers()) == 1
    assert all(
        h.get_name() != logging_config._ERROR_HANDLER_NAME
        for h in logging.getLogger("uvicorn").handlers
    )


def test_file_mode_has_no_dev_error_log(
    monkeypatch, tmp_path: Path, dev_error_log: Path
) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "logs"))

    logging_config.configure_logging()
    logging.getLogger("em_b.main").error("goes to api.log only")

    (handler,) = _app_handlers()
    assert handler.get_name() == logging_config._HANDLER_NAME
    assert not dev_error_log.exists()
