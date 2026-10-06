"""Tests for src.cache.semantic (Chroma-backed)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.cache.semantic import (
    COLLECTION_NAME,
    KEY_PREFIX,
    clear,
    ensure_index,
    lookup,
    store,
)
from src.models import QueryResponse, Source, TokenUsage


def _make_response(answer: str = "A") -> QueryResponse:
    return QueryResponse(
        answer=answer,
        sources=[Source(doc_id="p1", chunk_text="x", similarity_score=0.9)],
        confidence=0.9,
        model="gpt-4o-mini",
        tokens=TokenUsage(prompt_tokens=100, completion_tokens=20),
        cost_usd=0.001,
    )


def _mock_collection(*, count: int = 0, query_result: dict | None = None) -> MagicMock:
    """Build a mock Chroma collection in a controllable initial state."""
    col = MagicMock()
    col.count.return_value = count
    if query_result is not None:
        col.query.return_value = query_result
    return col


def _query_result(
    *,
    key: str,
    distance: float,
    response_json: str,
    created_at_iso: str | None = None,
    ttl_s: int = 3600,
    question: str = "any",
) -> dict:
    """Shape Chroma's collection.query() return value for tests."""
    return {
        "ids": [[key]],
        "distances": [[distance]],
        "documents": [[question]],
        "metadatas": [
            [
                {
                    "question": question,
                    "response": response_json,
                    "created_at": created_at_iso
                    or datetime.now(timezone.utc).isoformat(),
                    "ttl_s": ttl_s,
                }
            ]
        ],
    }


# --- ensure_index -----------------------------------------------------------


def test_ensure_index_calls_get_or_create_with_cosine():
    with patch("src.cache.semantic._client") as client:
        ensure_index()

    client.get_or_create_collection.assert_called_with(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"},
    )


# --- lookup -----------------------------------------------------------------


def test_lookup_returns_cached_response_above_threshold():
    cached = _make_response("cached answer")
    col = _mock_collection(
        count=1,
        query_result=_query_result(
            key="cache:abc",
            distance=0.02,  # similarity 0.98 ≥ 0.95
            response_json=cached.model_dump_json(),
        ),
    )
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.1] * 8
    ):
        client.get_or_create_collection.return_value = col

        result = lookup("How heavy is the Selkirk?")

    assert result is not None
    assert result.answer == "cached answer"
    assert result.cached is True


def test_lookup_returns_none_when_collection_empty():
    col = _mock_collection(count=0)
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.0] * 8
    ):
        client.get_or_create_collection.return_value = col

        assert lookup("anything") is None
    col.query.assert_not_called()  # short-circuits the embedding call


def test_lookup_returns_none_below_threshold():
    cached = _make_response()
    col = _mock_collection(
        count=1,
        query_result=_query_result(
            key="cache:x",
            distance=0.20,  # similarity 0.80 < 0.95
            response_json=cached.model_dump_json(),
        ),
    )
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.0] * 8
    ):
        client.get_or_create_collection.return_value = col

        assert lookup("question", threshold=0.95) is None


def test_lookup_respects_custom_threshold():
    cached = _make_response()
    col = _mock_collection(
        count=1,
        query_result=_query_result(
            key="cache:x",
            distance=0.15,  # similarity 0.85
            response_json=cached.model_dump_json(),
        ),
    )
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.0] * 8
    ):
        client.get_or_create_collection.return_value = col

        assert lookup("question", threshold=0.80) is not None
        assert lookup("question", threshold=0.95) is None


def test_lookup_evicts_stale_entry_and_misses():
    """If the nearest hit is older than its ttl_s, delete it inline + cache miss."""
    cached = _make_response()
    stale_iso = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    col = _mock_collection(
        count=1,
        query_result=_query_result(
            key="cache:stale",
            distance=0.02,
            response_json=cached.model_dump_json(),
            created_at_iso=stale_iso,
            ttl_s=60,  # stale by 60s
        ),
    )
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.0] * 8
    ):
        client.get_or_create_collection.return_value = col

        result = lookup("question")

    assert result is None
    col.delete.assert_called_once_with(ids=["cache:stale"])


def test_lookup_returns_response_when_within_ttl():
    cached = _make_response()
    fresh_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    col = _mock_collection(
        count=1,
        query_result=_query_result(
            key="cache:fresh",
            distance=0.02,
            response_json=cached.model_dump_json(),
            created_at_iso=fresh_iso,
            ttl_s=3600,
        ),
    )
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.0] * 8
    ):
        client.get_or_create_collection.return_value = col

        result = lookup("question")

    assert result is not None
    col.delete.assert_not_called()


def test_lookup_skips_ttl_check_when_ttl_zero():
    """ttl_s == 0 means 'never expire on read'."""
    cached = _make_response()
    ancient_iso = (
        datetime.now(timezone.utc) - timedelta(days=365)
    ).isoformat()
    col = _mock_collection(
        count=1,
        query_result=_query_result(
            key="cache:eternal",
            distance=0.02,
            response_json=cached.model_dump_json(),
            created_at_iso=ancient_iso,
            ttl_s=0,
        ),
    )
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.0] * 8
    ):
        client.get_or_create_collection.return_value = col

        assert lookup("question") is not None
    col.delete.assert_not_called()


# --- store ------------------------------------------------------------------


def test_store_upserts_with_required_metadata():
    response = _make_response()
    col = _mock_collection()
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.5] * 8
    ):
        client.get_or_create_collection.return_value = col

        key = store("How heavy is the Selkirk?", response, ttl_s=120)

    assert key.startswith(KEY_PREFIX)
    kwargs = col.upsert.call_args.kwargs
    assert kwargs["ids"] == [key]
    assert kwargs["documents"] == ["How heavy is the Selkirk?"]
    assert kwargs["embeddings"] == [[0.5] * 8]

    metadata = kwargs["metadatas"][0]
    assert metadata["question"] == "How heavy is the Selkirk?"
    assert metadata["ttl_s"] == 120
    assert "created_at" in metadata
    assert "answer" in metadata["response"]  # response stored as JSON


def test_store_persists_zero_ttl_in_metadata():
    response = _make_response()
    col = _mock_collection()
    with patch("src.cache.semantic._client") as client, patch(
        "src.cache.semantic.embed_query", return_value=[0.5] * 8
    ):
        client.get_or_create_collection.return_value = col

        store("q", response, ttl_s=0)

    metadata = col.upsert.call_args.kwargs["metadatas"][0]
    assert metadata["ttl_s"] == 0


# --- clear ------------------------------------------------------------------


def test_clear_deletes_all_cache_entries():
    col = _mock_collection(count=3)
    col.get.return_value = {"ids": ["cache:1", "cache:2", "cache:3"]}
    with patch("src.cache.semantic._client") as client:
        client.get_or_create_collection.return_value = col

        count = clear()

    assert count == 3
    col.delete.assert_called_once_with(ids=["cache:1", "cache:2", "cache:3"])


def test_clear_returns_zero_when_empty():
    col = _mock_collection(count=0)
    with patch("src.cache.semantic._client") as client:
        client.get_or_create_collection.return_value = col

        assert clear() == 0
    col.delete.assert_not_called()
