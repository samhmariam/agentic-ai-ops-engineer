"""Chroma vector-search cache for semantically similar queries.

Why this exists: a customer FAQ service sees many paraphrases of the same
question ("How heavy is the Selkirk?" / "What's the weight of the Selkirk
paddle?"). Embedding the query and checking a Chroma collection for a
near-neighbour cached response avoids an LLM call when the cache hits —
direct cost savings and lower latency.

Storage: a dedicated ``cache`` collection on the same on-disk
``PersistentClient`` as the document corpus (``settings.chroma_path``).
The same primitive — HNSW vector index — backs both, configured for
cosine distance so that ``1 - distance`` is a meaningful similarity
in [0, 1] and the rubric §10 thresholds (0.85 / 0.90 / 0.95) keep
their familiar interpretation.

Schema (per cache entry):
    id          — ``cache:<uuid4_hex>``
    document    — original query string (handy for inspection)
    embedding   — query vector (text-embedding-3-small produces 1536 dims)
    metadata    — ``{question, response (JSON), created_at (ISO), ttl_s}``

Tuning hooks: ``lookup(threshold=0.85)`` controls how similar a cached
query must be before it's served (lower = more hits, more false-positive
risk; higher = fewer hits, more safety). Default chosen so natural
paraphrases like "What's the weight of X?" / "How heavy is X?" / "X
weight please?" reliably hit each other without warming the cache first.
``store(ttl_s=3600)`` sets per-entry expiration; pass ``ttl_s=0`` to
keep entries until ``clear()`` or until manually deleted. TTL is
enforced lazily on read — no background sweep, no surprise eviction
between writes.
"""

import logging
import uuid
from datetime import datetime, timezone

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config import settings
from src.models import QueryResponse
from src.vectordb import embed_query

logger = logging.getLogger(__name__)

COLLECTION_NAME = "cache"
KEY_PREFIX = "cache:"

# See note in src/vectordb/store.py — silences chromadb 0.6.x posthog noise.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
_client = chromadb.PersistentClient(
    path=settings.chroma_path,
    settings=ChromaSettings(anonymized_telemetry=False),
)


def _collection() -> chromadb.Collection:
    """Get or create the cache collection (cosine HNSW)."""
    return _client.get_or_create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def ensure_index() -> None:
    """Create the cache collection if it doesn't already exist.

    Chroma builds the HNSW index automatically on first upsert; this
    function exists for API parity with the prior Redis-backed
    implementation and as an explicit creation hook.
    """
    _collection()


def lookup(question: str, *, threshold: float = 0.85) -> QueryResponse | None:
    """Return a cached ``QueryResponse`` if a similar, fresh query exists.

    Lazy TTL: if the nearest match is older than its stored ``ttl_s``,
    delete it inline and report a cache miss. Entries with ``ttl_s == 0``
    never expire on read.
    """
    collection = _collection()
    if collection.count() == 0:
        return None

    embedding = embed_query(question)
    results = collection.query(query_embeddings=[embedding], n_results=1)
    ids = results["ids"][0]
    if not ids:
        return None

    distance = float(results["distances"][0][0])
    similarity = 1.0 - distance
    if similarity < threshold:
        return None

    metadata = results["metadatas"][0][0]
    ttl_s = int(metadata.get("ttl_s", 0))
    created_at_iso = metadata.get("created_at")
    if ttl_s > 0 and created_at_iso:
        created_at = datetime.fromisoformat(created_at_iso)
        age_s = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age_s > ttl_s:
            collection.delete(ids=[ids[0]])
            return None

    response_json = metadata["response"]
    cached = QueryResponse.model_validate_json(response_json)
    return cached.model_copy(update={"cached": True})


def store(question: str, response: QueryResponse, *, ttl_s: int = 3600) -> str:
    """Cache the response under a fresh key. Returns the key written."""
    collection = _collection()
    embedding = embed_query(question)
    key = f"{KEY_PREFIX}{uuid.uuid4().hex}"
    collection.upsert(
        ids=[key],
        documents=[question],
        embeddings=[embedding],
        metadatas=[
            {
                "question": question,
                "response": response.model_dump_json(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ttl_s": ttl_s,
            }
        ],
    )
    return key


def clear() -> int:
    """Delete every entry in the cache collection. Returns the count removed."""
    collection = _collection()
    count_before = collection.count()
    if count_before == 0:
        return 0
    all_ids = collection.get()["ids"]
    if all_ids:
        collection.delete(ids=all_ids)
    return count_before
