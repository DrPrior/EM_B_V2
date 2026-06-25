from collections.abc import Generator

from fastapi import (  # type: ignore[import-untyped]
    APIRouter,
    Body,
    Depends,
    HTTPException,
    status,
)
from neo4j import Session  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from pipeline.ingest import ingest_project_data
from pipeline.load_manifest import load_manifests
from src.database.connection import Neo4jConnection
from src.services.ollama_bootstrap import (
    OllamaUnavailableError,
    ensure_models,
    wait_for_ollama,
)

# Trigger ingestion from the host:
#   curl.exe -s -X POST http://localhost:8000/admin/ingest | python -m json.tool
#
# To ingest a different directory, pass a JSON body with "data_root", e.g.:
#   curl.exe -s -X POST http://localhost:8000/admin/ingest \
#     -H "Content-Type: application/json" \
#     -d "{\"data_root\": \"/app/project_data\"}" | python -m json.tool
#
# Load manifest metadata (run after ingestion):
#   curl.exe -s -X POST http://localhost:8000/admin/load-manifest | python -m json.tool

router = APIRouter(prefix="/admin", tags=["admin"])


class IngestRequest(BaseModel):
    data_root: str = Field(
        default="/app/project_data",
        description="Absolute path to the directory to ingest.",
    )


class IngestResponse(BaseModel):
    files_processed: int
    chunks_created: int
    embeddings_stored: int
    errors: int


class ManifestLoadResponse(BaseModel):
    rows: int
    matched: int
    created: int
    errors: int


class BootstrapResponse(BaseModel):
    status: str


def get_db_session() -> Generator[Session, None, None]:
    connection = Neo4jConnection.get_instance()
    yield from connection.get_session_dependency()


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_200_OK)
def trigger_ingestion(
    request: IngestRequest = Body(default_factory=IngestRequest),
    session: Session = Depends(get_db_session),
) -> IngestResponse:
    """Run the ingestion pipeline against the specified data directory.

    Skips files that already have embedded chunks in the graph. Safe to call
    repeatedly — only unembedded files are processed.
    """
    try:
        stats = ingest_project_data(session, data_root=request.data_root)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}",
        ) from e
    return IngestResponse(**stats)


@router.post(
    "/load-manifest",
    response_model=ManifestLoadResponse,
    status_code=status.HTTP_200_OK,
)
def trigger_manifest_load(
    request: IngestRequest = Body(default_factory=IngestRequest),
    session: Session = Depends(get_db_session),
) -> ManifestLoadResponse:
    """Load document metadata from the MANIFEST*.md files into the graph.

    Run after ingestion: each manifest row is matched to existing File nodes by
    filename (hybrid mode), or a catalog node is created if none exists. Sets
    File.title and links Category, Source, Edition, WhyItMatters, and Validated
    nodes. Safe to call repeatedly — all writes are idempotent MERGEs.
    """
    try:
        stats = load_manifests(session, data_root=request.data_root)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Manifest load failed: {str(e)}",
        ) from e
    return ManifestLoadResponse(**stats)


@router.post(
    "/bootstrap-models",
    response_model=BootstrapResponse,
    status_code=status.HTTP_200_OK,
)
def trigger_model_bootstrap() -> BootstrapResponse:
    """Re-provision the host-native Ollama models without restarting the API.

    Waits for the host Ollama daemon, then pulls base models and builds the
    custom chat-model/embedding-model variants if any are missing. Idempotent —
    safe to call repeatedly; already-present models are skipped.
    """
    try:
        wait_for_ollama()
        ensure_models()
    except OllamaUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Model bootstrap failed: {str(e)}",
        ) from e
    return BootstrapResponse(status="ok")
