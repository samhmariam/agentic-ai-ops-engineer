"""Input/output guardrails — wraps the gateway with safety checks.

Two implementations ship side-by-side for pedagogy:

- ``guarded_route_query`` — rule-based (regex + heuristics). Predictable,
  offline, easy to read. ~100 lines of source.
- ``guarded_route_query_llmguard`` — library-based via LLM Guard (ProtectAI).
  ML-backed scanners (DeBERTa, Presidio, NLI). Catches novel attacks a
  rule-based version misses.

The Guardrails module content compares the two approaches. The HTTP
route in ``src.gateway.routes`` reproduces the same wiring inline; these
standalone wrappers are kept for tests and module-by-module exploration.
"""

from src.guardrails.input_guards import detect_pii, detect_prompt_injection
from src.guardrails.llm_guard import guarded_route_query_llmguard
from src.guardrails.output_guards import check_hallucination, is_off_topic
from src.guardrails.wrapper import (
    SAFE_BLOCKED_MESSAGE,
    SAFE_FILTERED_MESSAGE,
    guarded_route_query,
)

__all__ = [
    "detect_prompt_injection",
    "detect_pii",
    "check_hallucination",
    "is_off_topic",
    "guarded_route_query",
    "guarded_route_query_llmguard",
    "SAFE_BLOCKED_MESSAGE",
    "SAFE_FILTERED_MESSAGE",
]
