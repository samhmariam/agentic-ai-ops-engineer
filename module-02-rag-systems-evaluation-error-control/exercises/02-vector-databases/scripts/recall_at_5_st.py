"""Recall@5 against the MiniLM-built ``scikit_docs_st`` collection.

Usage (from the starter root, after ``scripts/load_data_st.py``):
    PYTHONPATH=. uv run python scripts/recall_at_5_st.py
    # or: make recall-st

Same subset and scoring as ``scripts/recall_at_5.py``; only the embedder
(local MiniLM) and the collection (``scikit_docs_st``) change. Queries
the collection directly because ``store.query`` always reads the
``scikit_docs`` alias, and converts cosine distance to similarity the
same way ``store.query`` does.
"""

from scripts.load_data_st import COLLECTION
from scripts.recall_at_5 import run
from src import store
from src.models import Source


def query_st(query_embedding: list[float], n_results: int) -> list[Source]:
    result = store.get_collection(COLLECTION).query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "distances"],
    )
    sources = [
        Source(doc_id=doc_id, chunk_text=document, similarity_score=1.0 - distance)
        for doc_id, document, distance in zip(
            result["ids"][0], result["documents"][0], result["distances"][0]
        )
    ]
    sources.sort(key=lambda s: s.similarity_score, reverse=True)
    return sources


def main() -> None:
    from scripts.embed_with_st import embed_query_st

    if store.get_collection(COLLECTION).count() == 0:
        raise SystemExit(f"'{COLLECTION}' is empty — run `make load-data-st` first.")
    run(embed_query_st, query_st, label=f"all-MiniLM-L6-v2 -> {COLLECTION}")


if __name__ == "__main__":
    main()
