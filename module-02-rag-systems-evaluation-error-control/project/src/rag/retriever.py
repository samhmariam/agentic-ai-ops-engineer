"""Retrieve relevant document chunks from the vector store."""

from src.models import Source
from src.vectordb import embed_query, query


def retrieve(question: str, top_k: int = 5) -> list[Source]:
    """Embed the question and return the top-k most similar product chunks."""
    query_embedding = embed_query(question)
    return query(query_embedding, n_results=top_k)
