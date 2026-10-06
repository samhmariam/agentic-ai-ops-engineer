"""Streaming chat completions and TTFT measurement.

Streaming mostly matters for *perceived* latency: the user sees the first
token in <500 ms instead of waiting 3+ s for the whole answer. Total
generation time is similar to the blocking call.

We measure both blocking and streaming and report the comparison so
students can see when streaming is worth the extra plumbing.
"""

import time
from typing import Iterator

from src.config import settings
from src.models import Source, TokenUsage
from src.pricing import compute_cost
from src.rag import run_pipeline
from src.rag.generator import _client, render_system_prompt
from src.rag.retriever import retrieve


def stream_completion(
    question: str, sources: list[Source], model: str
) -> Iterator[str | tuple[str, TokenUsage, float]]:
    """Yield each token as it arrives, then a final ``(answer, usage, cost)`` tuple.

    The OpenAI API returns ``usage`` only when ``stream_options={"include_usage": True}``
    is set; that final chunk has empty content but populated ``usage``.
    """
    system_prompt = render_system_prompt(sources)
    stream = _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        stream=True,
        stream_options={"include_usage": True},
    )

    parts: list[str] = []
    usage: TokenUsage | None = None

    for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                yield delta
        if getattr(chunk, "usage", None):
            usage = TokenUsage(
                prompt_tokens=chunk.usage.prompt_tokens,
                completion_tokens=chunk.usage.completion_tokens,
            )

    if usage is None:
        # Fallback when the provider didn't include usage in the stream
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0)

    answer = "".join(parts)
    cost = compute_cost(model, usage) if model in {"gpt-4o", "gpt-4o-mini"} else 0.0
    yield (answer, usage, cost)


def measure_ttft_streaming(
    question: str, model: str | None = None, top_k: int = 5
) -> dict:
    """Run one streaming generation; return ``{ttft_ms, total_ms, total_tokens}``."""
    chosen_model = model or settings.model_complex
    sources = retrieve(question, top_k=top_k)

    start = time.perf_counter()
    ttft_ms: float | None = None
    final: tuple[str, TokenUsage, float] | None = None

    for piece in stream_completion(question, sources, chosen_model):
        if isinstance(piece, tuple):
            final = piece
            break
        if ttft_ms is None:
            ttft_ms = (time.perf_counter() - start) * 1000

    total_ms = (time.perf_counter() - start) * 1000
    if final is None:
        final = ("", TokenUsage(prompt_tokens=0, completion_tokens=0), 0.0)

    return {
        "ttft_ms": ttft_ms or total_ms,
        "total_ms": total_ms,
        "total_tokens": final[1].total,
    }


def measure_ttft_blocking(
    question: str, model: str | None = None, top_k: int = 5
) -> dict:
    """Run one blocking pipeline; ``ttft_ms == total_ms`` because nothing streams."""
    chosen_model = model or settings.model_complex

    start = time.perf_counter()
    response = run_pipeline(question, model=chosen_model, top_k=top_k)
    total_ms = (time.perf_counter() - start) * 1000

    return {
        "ttft_ms": total_ms,
        "total_ms": total_ms,
        "total_tokens": response.tokens.total,
    }


def compare_ttft(
    question: str, model: str | None = None, top_k: int = 5
) -> dict:
    """Run both modes and compute the TTFT improvement."""
    blocking = measure_ttft_blocking(question, model=model, top_k=top_k)
    streaming = measure_ttft_streaming(question, model=model, top_k=top_k)

    delta_ms = blocking["ttft_ms"] - streaming["ttft_ms"]
    pct = (delta_ms / blocking["ttft_ms"] * 100) if blocking["ttft_ms"] else 0.0

    return {
        "blocking": blocking,
        "streaming": streaming,
        "ttft_improvement_ms": delta_ms,
        "ttft_improvement_pct": pct,
    }
