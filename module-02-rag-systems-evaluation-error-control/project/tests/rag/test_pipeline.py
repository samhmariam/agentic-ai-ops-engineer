"""Tests for src.rag.pipeline.run_pipeline."""

from unittest.mock import patch

from src.config import settings
from src.models import QueryResponse, Source, TokenUsage
from src.rag import run_pipeline


def test_run_pipeline_returns_full_query_response():
    sources = [
        Source(doc_id="p1", chunk_text="A", similarity_score=0.9),
        Source(doc_id="p2", chunk_text="B", similarity_score=0.7),
    ]
    usage = TokenUsage(prompt_tokens=100, completion_tokens=20)

    with patch("src.rag.pipeline.retrieve", return_value=sources) as retrieve_fn, \
         patch(
             "src.rag.pipeline.generate",
             return_value=("the answer", usage, 0.0042),
         ) as generate_fn:
        response = run_pipeline("Which paddle is best?", model="gpt-4o-mini", top_k=3)

    retrieve_fn.assert_called_once_with("Which paddle is best?", top_k=3)
    generate_fn.assert_called_once_with(
        "Which paddle is best?", sources, "gpt-4o-mini"
    )

    assert isinstance(response, QueryResponse)
    assert response.answer == "the answer"
    assert response.sources == sources
    assert response.confidence == 0.8  # mean of 0.9 and 0.7
    assert response.model == "gpt-4o-mini"
    assert response.tokens == usage
    assert response.cost_usd == 0.0042
    assert response.cached is False
    assert response.trace_id is None


def test_run_pipeline_defaults_to_complex_model():
    with patch("src.rag.pipeline.retrieve", return_value=[]), \
         patch(
             "src.rag.pipeline.generate",
             return_value=("ans", TokenUsage(prompt_tokens=1, completion_tokens=1), 0.0),
         ) as generate_fn:
        response = run_pipeline("Q")

    assert response.model == settings.model_complex
    generate_fn.assert_called_once_with("Q", [], settings.model_complex)


def test_run_pipeline_zero_confidence_when_no_sources():
    with patch("src.rag.pipeline.retrieve", return_value=[]), \
         patch(
             "src.rag.pipeline.generate",
             return_value=("ans", TokenUsage(prompt_tokens=1, completion_tokens=1), 0.0),
         ):
        response = run_pipeline("Q")

    assert response.sources == []
    assert response.confidence == 0.0
