"""Chroma vector-store client (in-process, persistent on disk).

``chromadb.PersistentClient`` writes a SQLite + parquet store under
``settings.chroma_path``. No server, no Docker — the same Collection
API as the HTTP client, so callers don't see a difference. Delete the
directory to reset; ``make load-data`` re-populates it.
"""

import logging
import os
import sys

# chromadb pulls onnxruntime via its default embedding function. onnxruntime
# probes /sys/class/drm/card0/device/vendor at C++ library init and emits a
# `GPU device discovery failed` WARNING on CPU-only hosts (most laptops, the
# Udacity Workspace). The warning is harmless but distracting for learners,
# so suppress fd-2 around the chromadb import — Python-level logging knobs
# don't reach the C++ logger. Subsequent `import chromadb` calls are no-ops
# (module-cached), so this one site silences the warning project-wide.
_saved_fd2 = os.dup(2)
_devnull = os.open(os.devnull, os.O_WRONLY)
try:
    os.dup2(_devnull, 2)
    import chromadb
    from chromadb.config import Settings as ChromaSettings
finally:
    sys.stderr.flush()
    os.dup2(_saved_fd2, 2)
    os.close(_devnull)
    os.close(_saved_fd2)

from src.config import settings
from src.models import Source

# anonymized_telemetry=False sets posthog.disabled=True inside chromadb,
# but a few capture() calls fire before that flag takes effect and crash
# against posthog 7.x's new signature. Silencing the telemetry logger
# itself suppresses the resulting stderr spam without changing behavior.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
_client = chromadb.PersistentClient(
    path=settings.chroma_path,
    settings=ChromaSettings(anonymized_telemetry=False),
)


def get_collection(name: str = "products") -> chromadb.Collection:
    """Get or create a Chroma collection by name.

    ``hnsw:space=cosine`` is load-bearing: OpenAI's ``text-embedding-3-small``
    returns unit-normalized vectors, and Chroma's default L2 space makes the
    ``similarity_score = 1 - distance`` convention return values outside
    ``[0, 1]``. The cache collection in ``src/cache/semantic.py`` pins the
    same metric for the same reason. Note that the metadata is only applied
    on collection creation; an existing L2-indexed directory must be deleted
    and re-loaded for the pin to take effect.
    """
    return _client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


def add(
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
    ids: list[str],
) -> None:
    """Upsert documents with pre-computed embeddings into the products collection."""
    collection = get_collection()
    collection.upsert(
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids,
    )


def query(query_embedding: list[float], n_results: int = 5) -> list[Source]:
    """Run a similarity search and return Source objects."""
    collection = get_collection()
    results = collection.query(query_embeddings=[query_embedding], n_results=n_results)

    sources = []
    for doc_id, text, distance in zip(
        results["ids"][0], results["documents"][0], results["distances"][0]
    ):
        sources.append(
            Source(
                doc_id=doc_id,
                chunk_text=text,
                similarity_score=max(0.0, 1.0 - distance),
            )
        )
    return sources


def delete(ids: list[str]) -> None:
    """Remove documents from the products collection by ID."""
    collection = get_collection()
    collection.delete(ids=ids)
