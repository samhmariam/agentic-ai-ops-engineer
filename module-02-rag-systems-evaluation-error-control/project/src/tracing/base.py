"""Shared helpers used by every tracing backend.

Each backend module (``phoenix_backend``, ``noop_backend``) exports the
same four names — ``init_tracing``, ``flush``, ``trace_rag_query``
decorator, and ``traced_pipeline`` — and the factory in
``src/tracing/__init__.py`` re-exports the one selected by
``settings.tracing_backend``.

This module collects the bits that don't depend on a specific backend.
"""

from src.models import QueryResponse


def summarize_sources(response: QueryResponse) -> list[dict]:
    """Compact list of (doc_id, similarity_score) dicts for trace metadata."""
    return [
        {"doc_id": s.doc_id, "similarity_score": s.similarity_score}
        for s in response.sources
    ]
