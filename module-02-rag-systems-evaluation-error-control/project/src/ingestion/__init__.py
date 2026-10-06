"""File-watcher ingestion: auto-ingest new product JSONs into Chroma."""

from src.ingestion.watcher import (
    REQUIRED_FIELDS,
    IngestionHandler,
    ingest_file,
    start_observer,
    start_watcher,
    validate_product,
)

__all__ = [
    "REQUIRED_FIELDS",
    "IngestionHandler",
    "ingest_file",
    "start_observer",
    "start_watcher",
    "validate_product",
]
