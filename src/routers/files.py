"""Source-file serving router.

Serves the original ingested documents so that cited sources in the chat UI can
be opened with a click. Files are streamed straight from the configured
``settings.data_root`` (the same directory the ingestion pipeline reads from).

Security note: this build is intended to run locally on the user's own machine,
so the files are served without authentication. A path-traversal guard is still
applied so a crafted request cannot escape ``data_root`` and read arbitrary
files off the host.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from src.core.config import settings

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_path:path}")
def get_source_file(file_path: str) -> FileResponse:
    """Return an ingested source file by its path relative to ``data_root``.

    Args:
        file_path: Path of the file relative to ``settings.data_root`` (the
            same value carried on each chat source's ``url``).

    Returns:
        A ``FileResponse`` streaming the requested file.

    Raises:
        HTTPException: 403 if the resolved path escapes ``data_root``, 404 if
            the file does not exist.
    """
    root = Path(settings.data_root).resolve()
    target = (root / file_path).resolve()

    # Path-traversal guard: the resolved target must stay inside data_root.
    if root != target and root not in target.parents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requested path is outside the data root.",
        )

    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source file not found: {file_path}",
        )

    # inline so PDFs/text open in the browser; filename hints a sensible save name.
    return FileResponse(
        target,
        filename=target.name,
        content_disposition_type="inline",
    )
