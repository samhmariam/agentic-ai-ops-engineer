"""Vector database package — chunking, embedding, and Chroma storage."""

from src.vectordb.chunker import chunk_product
from src.vectordb.embedder import embed, embed_query
from src.vectordb.store import get_collection, add, query, delete

__all__ = [
    "chunk_product",
    "embed",
    "embed_query",
    "get_collection",
    "add",
    "query",
    "delete",
]
