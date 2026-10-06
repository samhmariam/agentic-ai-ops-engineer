"""Tests for src.rag.retriever."""

from unittest.mock import patch

from src.models import Source
from src.rag import retrieve


def test_retrieve_embeds_query_and_returns_top_k():
    fake_embedding = [0.1, 0.2, 0.3]
    fake_sources = [
        Source(doc_id="p1", chunk_text="Selkirk AMPED S2 paddle", similarity_score=0.9),
        Source(doc_id="p2", chunk_text="Joola Hyperion paddle", similarity_score=0.8),
    ]

    with patch("src.rag.retriever.embed_query", return_value=fake_embedding) as embed, \
         patch("src.rag.retriever.query", return_value=fake_sources) as query_fn:
        result = retrieve("What is the lightest paddle?", top_k=2)

    embed.assert_called_once_with("What is the lightest paddle?")
    query_fn.assert_called_once_with(fake_embedding, n_results=2)
    assert result == fake_sources


def test_retrieve_uses_default_top_k():
    with patch("src.rag.retriever.embed_query", return_value=[0.0]), \
         patch("src.rag.retriever.query", return_value=[]) as query_fn:
        retrieve("any question")

    query_fn.assert_called_once_with([0.0], n_results=5)
