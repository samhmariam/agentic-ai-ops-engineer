"""Tests for src.vectordb.store."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.vectordb import add, delete, get_collection, query
from src.models import Source


def _query_results(ids: list[str], docs: list[str], distances: list[float]):
    """Mimic the dict shape Chroma returns."""
    return {
        "ids": [ids],
        "documents": [docs],
        "distances": [distances],
    }


def test_get_collection_returns_or_creates_named_collection():
    with patch("src.vectordb.store._client") as client:
        fake_col = MagicMock()
        client.get_or_create_collection.return_value = fake_col

        result = get_collection("products")

    client.get_or_create_collection.assert_called_once_with(
        "products", metadata={"hnsw:space": "cosine"}
    )
    assert result is fake_col


def test_add_upserts_with_all_arrays():
    with patch("src.vectordb.store._client") as client:
        fake_col = MagicMock()
        client.get_or_create_collection.return_value = fake_col

        add(
            documents=["doc1", "doc2"],
            embeddings=[[0.1], [0.2]],
            metadatas=[{"a": 1}, {"a": 2}],
            ids=["id1", "id2"],
        )

    fake_col.upsert.assert_called_once_with(
        documents=["doc1", "doc2"],
        embeddings=[[0.1], [0.2]],
        metadatas=[{"a": 1}, {"a": 2}],
        ids=["id1", "id2"],
    )


def test_query_converts_distances_to_similarity_scores():
    with patch("src.vectordb.store._client") as client:
        fake_col = MagicMock()
        fake_col.query.return_value = _query_results(
            ids=["p1", "p2"],
            docs=["chunk one", "chunk two"],
            distances=[0.1, 0.3],
        )
        client.get_or_create_collection.return_value = fake_col

        result = query([0.5, 0.5], n_results=2)

    fake_col.query.assert_called_once_with(query_embeddings=[[0.5, 0.5]], n_results=2)
    assert len(result) == 2
    assert all(isinstance(s, Source) for s in result)
    # similarity = 1 - distance
    assert result[0].doc_id == "p1"
    assert result[0].chunk_text == "chunk one"
    assert result[0].similarity_score == 0.9
    assert result[1].similarity_score == 0.7


def test_query_clamps_similarity_score_at_zero():
    # A distance > 1.0 (possible if a collection was created with an L2 space
    # instead of cosine, or if upstream weirdness produces it) would make the
    # naive ``1 - distance`` go negative. The clamp keeps ``similarity_score``
    # in ``[0, 1]`` so downstream "confidence" stays a meaningful number.
    with patch("src.vectordb.store._client") as client:
        fake_col = MagicMock()
        fake_col.query.return_value = _query_results(
            ids=["p1", "p2"],
            docs=["chunk one", "chunk two"],
            distances=[0.4, 1.7],
        )
        client.get_or_create_collection.return_value = fake_col

        result = query([0.5, 0.5], n_results=2)

    assert result[0].similarity_score == 0.6
    assert result[1].similarity_score == 0.0


def test_delete_calls_collection_delete():
    with patch("src.vectordb.store._client") as client:
        fake_col = MagicMock()
        client.get_or_create_collection.return_value = fake_col

        delete(["id1", "id2"])

    fake_col.delete.assert_called_once_with(ids=["id1", "id2"])
