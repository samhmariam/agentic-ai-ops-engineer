"""Thin wrapper around OpenAI's embeddings API."""

from openai import OpenAI

from src.config import settings

_client = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url or None,
)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts and return their vector representations."""
    response = _client.embeddings.create(
        input=texts, model=settings.embedding_model
    )
    return [item.embedding for item in response.data]


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    return embed([text])[0]
