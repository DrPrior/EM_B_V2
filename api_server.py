"""Alternative API server entry point.

This module provides an alternative way to start the FastAPI application.
The default method uses uvicorn directly via the Dockerfile CMD.
This file is kept for backward compatibility and alternative deployment scenarios.
"""

import uvicorn

from src.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
