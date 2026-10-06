"""Tests for src.vectordb.embedder."""

from types import SimpleNamespace
from unittest.mock import patch

from src.vectordb import embed, embed_query


def _embeddings_response(*vectors: list[float]):
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=v) for v in vectors]
    )


def test_embed_returns_one_vector_per_input():
    with patch("src.vectordb.embedder._client") as client:
        client.embeddings.create.return_value = _embeddings_response(
            [0.1, 0.2], [0.3, 0.4]
        )

        result = embed(["a", "b"])

    client.embeddings.create.assert_called_once()
    call_kwargs = client.embeddings.create.call_args.kwargs
    assert call_kwargs["input"] == ["a", "b"]
    assert call_kwargs["model"] == "text-embedding-3-small"
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_query_returns_first_vector():
    with patch("src.vectordb.embedder._client") as client:
        client.embeddings.create.return_value = _embeddings_response([0.5, 0.6, 0.7])

        result = embed_query("hello")

    assert result == [0.5, 0.6, 0.7]
    assert client.embeddings.create.call_args.kwargs["input"] == ["hello"]
