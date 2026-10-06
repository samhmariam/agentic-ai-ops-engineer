"""Semantic cache (Chroma collection) — implements the Semantic Caching module."""

from src.cache.semantic import (
    COLLECTION_NAME,
    KEY_PREFIX,
    clear,
    ensure_index,
    lookup,
    store,
)
from src.cache.wrapper import cached_route_query

__all__ = [
    "COLLECTION_NAME",
    "KEY_PREFIX",
    "ensure_index",
    "lookup",
    "store",
    "clear",
    "cached_route_query",
]
