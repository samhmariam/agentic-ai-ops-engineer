"""End-to-end RAG flow: retrieve -> prompt -> generate -> respond."""

from src.config import settings
from src.models import QueryResponse
from src.rag.generator import generate
from src.rag.retriever import retrieve


def run_pipeline(
    question: str, model: str | None = None, top_k: int = 5
) -> QueryResponse:
    """Run the full RAG pipeline and return a structured QueryResponse."""
    chosen_model = model or settings.model_complex
    sources = retrieve(question, top_k=top_k)
    answer, usage, cost = generate(question, sources, chosen_model)
    confidence = (
        sum(s.similarity_score for s in sources) / len(sources) if sources else 0.0
    )
    return QueryResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        model=chosen_model,
        tokens=usage,
        cost_usd=cost,
    )
