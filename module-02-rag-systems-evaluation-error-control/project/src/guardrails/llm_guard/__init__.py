"""LLM Guard (ProtectAI) implementation of the same four checks as the regex version.

Why a second implementation:
- The course originally specified Guardrails AI Hub validators, but the
  Hub's prompt-injection validator (Rebuff-backed) was archived May 2025 and
  requires Pinecone — a classroom-hostile dependency.
- LLM Guard ships ML-backed scanners (DeBERTa for injection, Presidio for PII,
  transformer classifiers for topic + factuality) that all run locally with no
  external accounts.
- Shipping both implementations lets students diff rule-based vs. ML-based
  validation side-by-side without leaving the repo.

Tests mock the scanner classes in ``tests/conftest.py``; real runs download
~400 MB of models on first scan.
"""

from src.guardrails.llm_guard.input_guards import detect_pii, detect_prompt_injection
from src.guardrails.llm_guard.output_guards import check_hallucination, is_off_topic
from src.guardrails.llm_guard.wrapper import guarded_route_query_llmguard

__all__ = [
    "detect_prompt_injection",
    "detect_pii",
    "check_hallucination",
    "is_off_topic",
    "guarded_route_query_llmguard",
]
