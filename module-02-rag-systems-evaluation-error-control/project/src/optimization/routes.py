"""Streaming HTTP route — POST /query/stream as Server-Sent Events.

Lives in the optimization package, not the gateway, to keep the
forward-dependency rule: the gateway module is taught before
optimization, so the gateway code shouldn't depend on optimization.
``src.gateway.app`` mounts this router via ``include_router`` the same
way it mounts the cost dashboard — that's the documented exception.

Input guards run before the stream is opened: prompt-injection blocks
return a single ``data:`` event with ``blocked_by`` set, and PII in the
question is redacted before retrieval and generation. Output guards over
streamed tokens are intentionally deferred — applying them on a partial
answer is a follow-up exercise in the optimization or guardrails module.
"""

import json
from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.cost.tracker import log_request
from src.gateway.classifier import classify
from src.gateway.router import select_model
from src.guardrails.llm_guard.input_guards import detect_pii, detect_prompt_injection
from src.guardrails.wrapper import SAFE_BLOCKED_MESSAGE, _safe_response
from src.models import QueryResponse
from src.optimization.streaming import stream_completion
from src.rag.retriever import retrieve

router = APIRouter()


class StreamQueryRequest(BaseModel):
    """Request body for ``POST /query/stream``.

    Same shape and same caps as ``QueryRequest`` in the gateway's blocking
    route. Kept as a separate class so the streaming endpoint can evolve
    its own validation (e.g. a future ``stream_options`` field) without
    touching the blocking route.
    """

    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(5, ge=1, le=20)


def _sse_event(payload: dict) -> str:
    """Serialize a dict as a Server-Sent Event ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


def _blocked_stream(blocked: QueryResponse) -> Iterator[str]:
    """Yield exactly one ``done`` event for an injection-blocked request.

    Streaming-route equivalent of the blocking route's ``_safe_response``
    short-circuit: no tokens, no LLM call, just the safe ``QueryResponse``
    with ``blocked_by`` set so the client can render the refusal.
    """
    yield _sse_event({"type": "done", "response": json.loads(blocked.model_dump_json())})


def _stream(question: str, top_k: int, pii_found: list[str]) -> Iterator[str]:
    """Generator that yields SSE-formatted events for one query."""
    query_type = classify(question)
    model = select_model(query_type)
    sources = retrieve(question, top_k=top_k)
    confidence = (
        sum(s.similarity_score for s in sources) / len(sources) if sources else 0.0
    )

    answer = ""
    usage = None
    cost = 0.0

    for piece in stream_completion(question, sources, model):
        if isinstance(piece, tuple):
            answer, usage, cost = piece
            break
        yield _sse_event({"type": "token", "content": piece})

    response = QueryResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        model=model,
        tokens=usage,
        cost_usd=cost,
        blocked_by=(
            f"pii_redacted: {','.join(pii_found)}" if pii_found else None
        ),
    )
    log_request(model, usage, cost, query_type)
    yield _sse_event({"type": "done", "response": json.loads(response.model_dump_json())})


@router.post("/query/stream")
async def query_stream(request: StreamQueryRequest) -> StreamingResponse:
    """Stream a FAQ answer token-by-token via Server-Sent Events.

    Input guards run before any token is emitted (injection short-circuits
    to a single ``done`` event; PII is redacted in-place). Output guards
    over a partial token stream are intentionally deferred — applying NLI
    or banned-topics checks across an in-flight stream is a follow-up
    exercise in the optimization module.
    """
    if reason := detect_prompt_injection(request.question):
        blocked = _safe_response(SAFE_BLOCKED_MESSAGE, blocked_by=reason)
        return StreamingResponse(
            _blocked_stream(blocked),
            media_type="text/event-stream",
        )
    cleaned, pii_found = detect_pii(request.question)
    return StreamingResponse(
        _stream(cleaned, request.top_k, pii_found),
        media_type="text/event-stream",
    )
