"""Cache-then-route wrapper. Same composition pattern as ``traced_pipeline``.

This wrapper composes the cache around the gateway without modifying the
gateway. The pattern (non-invasive instrumentation; see
``docs/solutions/best-practices/non-invasive-decorator-instrumentation-tracing-20260423.md``)
keeps ``src.gateway.router`` unaware of caching, so the gateway module
stays readable on its own. The production HTTP route in
``src.gateway.routes`` reproduces the cache-around-router composition
inline for the same reason a learner would: making the layering visible
at the request boundary.
"""

from src.cache.semantic import lookup, store
from src.gateway.router import route_query
from src.models import QueryResponse


def cached_route_query(
    question: str,
    top_k: int = 5,
    *,
    threshold: float = 0.85,
    ttl_s: int = 3600,
) -> QueryResponse:
    """Check the cache first; on miss, run the gateway and cache the result."""
    if cached := lookup(question, threshold=threshold):
        return cached

    response = route_query(question, top_k=top_k)
    store(question, response, ttl_s=ttl_s)
    return response
