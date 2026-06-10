"""Data ingestion pipeline module.

Exports the main ingestion function for use in FastAPI lifespan.
"""

from pipeline.ingest import ingest_project_data

__all__ = ["ingest_project_data"]
