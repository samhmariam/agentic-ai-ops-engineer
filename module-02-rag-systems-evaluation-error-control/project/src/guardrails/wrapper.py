"""Glue: ``guarded_route_query`` wraps the gateway with input/output guards.

Per assumption A6, blocked or filtered requests return HTTP 200 with a
safe ``QueryResponse`` (no sources, zero confidence, ``blocked_by`` set
to identify which guard triggered).
"""

from src.gateway.router import route_query
from src.guardrails.input_guards import detect_pii, detect_prompt_injection
from src.guardrails.output_guards import check_hallucination, is_off_topic
from src.models import QueryResponse, TokenUsage

SAFE_BLOCKED_MESSAGE = (
    "I can't help with that request. Please ask about ThirdShotHub products."
)
SAFE_FILTERED_MESSAGE = (
    "I'm not confident in an answer based on the available product information. "
    "Please rephrase or contact support."
)


def _safe_response(message: str, blocked_by: str) -> QueryResponse:
    return QueryResponse(
        answer=message,
        sources=[],
        confidence=0.0,
        model="",
        tokens=TokenUsage(prompt_tokens=0, completion_tokens=0),
        cost_usd=0.0,
        blocked_by=blocked_by,
    )


def guarded_route_query(question: str, top_k: int = 5) -> QueryResponse:
    """Run input guards → gateway → output guards. Safe response on any block."""
    # --- Input guards ---
    if reason := detect_prompt_injection(question):
        return _safe_response(SAFE_BLOCKED_MESSAGE, blocked_by=reason)

    cleaned, pii_found = detect_pii(question)
    # PII is redacted, not blocked — the cleaned question continues.

    # --- Gateway ---
    response = route_query(cleaned, top_k=top_k)

    # --- Output guards ---
    if reason := check_hallucination(response.answer, response.sources):
        return _safe_response(SAFE_FILTERED_MESSAGE, blocked_by=reason)
    if reason := is_off_topic(response.answer):
        return _safe_response(SAFE_FILTERED_MESSAGE, blocked_by=reason)

    if pii_found:
        # Annotate without otherwise modifying the response.
        return response.model_copy(
            update={"blocked_by": f"pii_redacted: {','.join(pii_found)}"}
        )
    return response
