"""Resource paths that must resolve both from source and inside a frozen bundle.

The decontainerized app runs two ways: from source under ``uvicorn`` (a venv),
and — once packaged — as a PyInstaller executable. Files the app reads at runtime
(the Ollama ``Modelfile`` variants, the static web UI) live at repo-relative
paths that only work from source. These helpers resolve them correctly in both
cases so nothing depends on the current working directory.

Packaging note: a frozen build must bundle these resources so they land under
:func:`resource_root` — e.g. PyInstaller ``--add-data`` for ``Modelfile``,
``Modelfile.embeddings`` (at the root) and ``src/static`` (preserving that
subpath). See ``docs/DECONTAINERIZE_PLAN.md`` (Workstream E).
"""

import sys
from pathlib import Path


def resource_root() -> Path:
    """Directory under which bundled runtime resources live.

    - From source: the repository root (two levels up from ``src/core``).
    - Frozen (PyInstaller): ``sys._MEIPASS`` for a one-file build, else the
      directory holding the executable for a one-dir build.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def modelfile_path(name: str) -> Path:
    """Absolute path to a Modelfile (``Modelfile`` / ``Modelfile.embeddings``)."""
    return resource_root() / name


def static_dir() -> Path:
    """Absolute path to the static web UI directory served at ``/``."""
    return resource_root() / "src" / "static"


def default_log_dir() -> Path | None:
    """Fallback log directory when ``LOG_DIR`` is not set.

    - From source: None — logs go to the console.
    - Frozen: a ``logs`` directory beside the executable. The one-dir bundle is
      unpacked under the user's app-data directory, so it is writable. The
      Electron shell normally overrides this with ``LOG_DIR``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "logs"
    return None
