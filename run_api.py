"""Frozen-app entry point for the native API.

PyInstaller freezes this rather than the ``uvicorn`` CLI: it hands the app object
to ``uvicorn.run`` directly (no import-string, no ``--reload``) so it works inside
a one-dir bundle. Host/port come from the environment so the Electron supervisor
can override them. From source you can also run it directly: ``python run_api.py``.
"""

import os

import uvicorn

from src.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
