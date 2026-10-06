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


def test_select_model_maps_simple_to_mini_and_complex_to_full():
    assert select_model("simple") == settings.model_simple
    assert select_model("complex") == settings.model_complex


@pytest.mark.parametrize(
    "query_type,expected_model",
    [("simple", "gpt-4o-mini"), ("complex", "gpt-4o")],
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
