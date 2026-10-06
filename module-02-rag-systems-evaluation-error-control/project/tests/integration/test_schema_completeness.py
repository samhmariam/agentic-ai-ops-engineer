"""Schema-level checks that survive refactors.

If someone removes a field from QueryResponse or returns the wrong type
from a wrapper, these tests fire before any per-package test masks it.
"""

from src.guardrails import guarded_route_query
from src.guardrails.llm_guard import guarded_route_query_llmguard
from src.models import QueryResponse


REQUIRED_QUERYRESPONSE_FIELDS: set[str] = {
    "answer",
    "sources",
    "confidence",
    "model",
    "tokens",
    "cost_usd",
    "cached",
    "trace_id",
    "blocked_by",
}


def test_query_response_has_expected_field_set():
    assert set(QueryResponse.model_fields.keys()) == REQUIRED_QUERYRESPONSE_FIELDS


def test_query_response_default_values_are_sane():
    fields = QueryResponse.model_fields
    assert fields["cached"].default is False
    assert fields["trace_id"].default is None
    assert fields["blocked_by"].default is None


def test_guarded_route_query_signature_returns_query_response_annotation():
    import inspect

    for fn in (guarded_route_query, guarded_route_query_llmguard):
        signature = inspect.signature(fn)
        # Either return annotation is QueryResponse or it's a string forward ref
        annotation = signature.return_annotation
        if isinstance(annotation, str):
            assert "QueryResponse" in annotation
        else:
            assert annotation is QueryResponse


def test_traced_pipeline_signature_returns_query_response():
    import inspect

    from src.tracing import traced_pipeline

    annotation = inspect.signature(traced_pipeline).return_annotation
    if isinstance(annotation, str):
        assert "QueryResponse" in annotation
    else:
        assert annotation is QueryResponse


def test_cached_route_query_signature_returns_query_response():
    import inspect

    from src.cache import cached_route_query

    annotation = inspect.signature(cached_route_query).return_annotation
    if isinstance(annotation, str):
        assert "QueryResponse" in annotation
    else:
        assert annotation is QueryResponse
