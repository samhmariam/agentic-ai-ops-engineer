"""Tests for src.cache.wrapper.cached_route_query."""

from unittest.mock import patch

from src.cache import cached_route_query
from src.models import QueryResponse, Source, TokenUsage


def _response(cached: bool = False, answer: str = "live answer") -> QueryResponse:
    return QueryResponse(
        answer=answer,
        sources=[Source(doc_id="p1", chunk_text="x", similarity_score=0.9)],
        confidence=0.9,
        model="gpt-4o-mini",
        tokens=TokenUsage(prompt_tokens=100, completion_tokens=20),
        cost_usd=0.001,
        cached=cached,
    )


def test_cache_hit_returns_cached_response_without_calling_route_query():
    cached = _response(cached=True, answer="from cache")

    with patch("src.cache.wrapper.lookup", return_value=cached) as lookup, \
         patch("src.cache.wrapper.route_query") as route, \
         patch("src.cache.wrapper.store") as store:
        result = cached_route_query("Q", top_k=3)

    lookup.assert_called_once_with("Q", threshold=0.85)
    route.assert_not_called()
    store.assert_not_called()
    assert result is cached


def test_cache_miss_runs_route_query_and_stores_result():
    fresh = _response(answer="freshly computed")

    with patch("src.cache.wrapper.lookup", return_value=None), \
         patch("src.cache.wrapper.route_query", return_value=fresh) as route, \
         patch("src.cache.wrapper.store") as store:
        result = cached_route_query("Q", top_k=3)

    route.assert_called_once_with("Q", top_k=3)
    store.assert_called_once_with("Q", fresh, ttl_s=3600)
    assert result is fresh


def test_custom_threshold_and_ttl_are_forwarded():
    with patch("src.cache.wrapper.lookup", return_value=None) as lookup, \
         patch("src.cache.wrapper.route_query", return_value=_response()), \
         patch("src.cache.wrapper.store") as store:
        cached_route_query("Q", threshold=0.80, ttl_s=60)

    assert lookup.call_args.kwargs["threshold"] == 0.80
    assert store.call_args.kwargs["ttl_s"] == 60
