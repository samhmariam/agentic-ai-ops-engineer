"""LLM-judge variant of the output guards.

Asks gpt-4o-mini "does this answer follow from the source?" with a
structured JSON output. Replaces the NLI-based ``FactualConsistency``
scanner as the live default — see
``docs/verifications/2026-04-29-factuality-threshold-tuning.md`` for the
calibration evidence motivating the swap.

The NLI scanner code at ``src.guardrails.llm_guard`` remains in the
tree as a teaching reference; only the live ``/query`` import is
swapped.
"""

from src.guardrails.llm_judge.output_guards import check_hallucination, is_off_topic

__all__ = ["check_hallucination", "is_off_topic"]
