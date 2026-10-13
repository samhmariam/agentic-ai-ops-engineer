"""Tests for src.gateway.router."""

from unittest.mock import patch

import pytest

from src.config import settings
from src.gateway.router import route_query, select_model
from src.models import QueryResponse, Source, TokenUsage


def _make_response(model: str, cost: float = 0.001) -> QueryResponse:
    return QueryResponse(
        answer="A",
        sources=[Source(doc_id="p1", chunk_text="x", similarity_score=0.9)],
        confidence=0.9,
        model=model,
        tokens=TokenUsage(prompt_tokens=100, completion_tokens=20),
        cost_usd=cost,
        trace_id="trace-1",
    )


def test_select_model_maps_each_tier_to_its_model():
    assert select_model("budget") == settings.model_budget
    assert select_model("simple") == settings.model_simple
    assert select_model("complex") == settings.model_complex


@pytest.mark.parametrize(
    "query_type,expected_model",
    [("budget", "gpt-4.1-nano"), ("simple", "gpt-4o-mini"), ("complex", "gpt-4o")],
)
def test_route_query_dispatches_to_correct_model(query_type, expected_model):
    response = _make_response(expected_model)

    with patch("src.gateway.router.classify", return_value=query_type) as classifier, \
         patch("src.gateway.router.traced_pipeline", return_value=response) as traced, \
         patch("src.gateway.router.log_request") as log:
        result = route_query("Q", top_k=3)

    classifier.assert_called_once_with("Q")
    traced.assert_called_once_with("Q", model=expected_model, top_k=3)
    log.assert_called_once_with(
        expected_model, response.tokens, response.cost_usd, query_type
    )
    assert result is response


def test_route_query_default_top_k_is_5():
    response = _make_response("gpt-4o-mini")
    with patch("src.gateway.router.classify", return_value="simple"), \
         patch("src.gateway.router.traced_pipeline", return_value=response) as traced, \
         patch("src.gateway.router.log_request"):
        route_query("Q")

    assert traced.call_args.kwargs["top_k"] == 5


def test_route_query_puts_classification_and_pipeline_in_one_trace():
    """The classifier call must share the request trace, not start its own."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    seen: dict[str, object] = {}

    def fake_classify(question):
        seen["classify"] = otel_trace.get_current_span().get_span_context()
        return "complex"

    def fake_pipeline(question, model, top_k):
        seen["pipeline"] = otel_trace.get_current_span().get_span_context()
        return _make_response(model)

    with patch("src.gateway.router.otel_trace.get_tracer", return_value=tracer), \
         patch("src.gateway.router.classify", side_effect=fake_classify), \
         patch("src.gateway.router.traced_pipeline", side_effect=fake_pipeline), \
         patch("src.gateway.router.log_request"):
        route_query("Compare A and B")

    spans = {s.name: s for s in exporter.get_finished_spans()}
    route, classification = spans["route_query"], spans["classification"]
    assert classification.parent.span_id == route.context.span_id
    assert classification.attributes["rag.query_type"] == "complex"
    assert route.attributes["rag.model"] == settings.model_complex
    # classify ran inside the classification span; the pipeline inside route_query
    assert seen["classify"].span_id == classification.context.span_id
    assert seen["pipeline"].span_id == route.context.span_id
    assert seen["classify"].trace_id == seen["pipeline"].trace_id
