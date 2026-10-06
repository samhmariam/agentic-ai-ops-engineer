"""LLM Guard variant of ``guarded_route_query`` — same flow, different scanners."""

from src.gateway.router import route_query
from src.guardrails.llm_guard.input_guards import (
    detect_pii,
    detect_prompt_injection,
)
from src.guardrails.llm_guard.output_guards import check_hallucination, is_off_topic
from src.guardrails.wrapper import (
    SAFE_BLOCKED_MESSAGE,
    SAFE_FILTERED_MESSAGE,
    _safe_response,
)
from src.models import QueryResponse


def guarded_route_query_llmguard(question: str, top_k: int = 5) -> QueryResponse:
    """Run LLM Guard input guards → gateway → LLM Guard output guards."""
    # --- Input ---
    if reason := detect_prompt_injection(question):
        return _safe_response(SAFE_BLOCKED_MESSAGE, blocked_by=reason)

    cleaned, pii_found = detect_pii(question)

    # --- Gateway ---
    response = route_query(cleaned, top_k=top_k)

    # --- Output ---
    if reason := check_hallucination(response.answer, response.sources):
        return _safe_response(SAFE_FILTERED_MESSAGE, blocked_by=reason)
    if reason := is_off_topic(response.answer):
        return _safe_response(SAFE_FILTERED_MESSAGE, blocked_by=reason)

    if pii_found:
        return response.model_copy(
            update={"blocked_by": f"pii_redacted: {','.join(pii_found)}"}
        )
    return response
