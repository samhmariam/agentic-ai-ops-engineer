"""Tiered model routing — classify, dispatch to nano, mini or 4o, log cost.

This is the integration hub: classify → choose model → run traced
pipeline → log per-request cost. Deliverable #3 of the project proposal
(measurable savings from tiered routing) is realised here.
"""

from opentelemetry import trace as otel_trace

from src.config import settings
from src.cost.tracker import log_request
from src.gateway.classifier import QueryType, classify
from src.models import QueryResponse
from src.tracing import traced_pipeline


def select_model(query_type: QueryType) -> str:
    """Map a query type to the configured model name."""
    return {
        "budget": settings.model_budget,
        "simple": settings.model_simple,
    }.get(query_type, settings.model_complex)


def route_query(question: str, top_k: int = 5) -> QueryResponse:
    """Full request flow: classify, dispatch, trace, log.

    Classification and the traced pipeline share one ``route_query``
    span, so the classifier's auto-instrumented ``ChatCompletion`` lands
    in the same trace as retrieval and generation instead of starting a
    separate root trace. With no tracer provider configured,
    ``get_tracer`` returns a no-op tracer and the spans are dropped.
    """
    tracer = otel_trace.get_tracer("src.gateway.router")
    with tracer.start_as_current_span("route_query") as route_span:
        with tracer.start_as_current_span("classification") as span:
            span.set_attribute("input.value", question)
            query_type = classify(question)
            span.set_attribute("rag.query_type", query_type)
        model = select_model(query_type)
        route_span.set_attribute("rag.query_type", query_type)
        route_span.set_attribute("rag.model", model)
        response = traced_pipeline(question, model=model, top_k=top_k)
    log_request(model, response.tokens, response.cost_usd, query_type)
    return response
