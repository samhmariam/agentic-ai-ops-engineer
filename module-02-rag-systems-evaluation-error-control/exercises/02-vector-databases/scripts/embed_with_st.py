"""Local sentence-transformers embedder for the embedder-swap exercise.

Lives beside (not inside) ``src/embedder.py`` so the production OpenAI
embedder stays untouched for the side-by-side comparison.

``normalize_embeddings=True`` is the sentence-transformers equivalent of
OpenAI's built-in unit normalisation — without it, the cosine space the
Chroma collection is pinned to returns distances outside [0, 2].
"""

from sentence_transformers import SentenceTransformer

MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM: int = 384

_model = SentenceTransformer(MODEL_NAME)


def embed_query_st(text: str) -> list[float]:
    vec = _model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_st(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    return _model.encode(
        texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=True
    ).tolist()
