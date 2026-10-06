"""Output-side validators via LLM Guard scanners.

- ``BanTopics`` uses a zero-shot transformer classifier (`MoritzLaurer/deberta-v3-base-zeroshot-v2.0-distilled`)
  to detect when the answer is about a banned topic. We populate the ban list
  with off-topic subjects likely to leak into product-FAQ outputs.
- ``FactualConsistency`` uses a natural-language-inference (NLI) classifier to
  decide whether the answer is entailed by, neutral toward, or contradicts the
  concatenated retrieved source text.

Both scanners follow LLM Guard's output signature:
    scan(prompt: str, output: str) -> (sanitized_output, is_valid: bool, risk_score: float)
"""

from llm_guard.output_scanners import BanTopics, FactualConsistency

from src.config import settings
from src.models import Source

# Topics that should never show up in a ThirdShotHub product answer. BanTopics
# treats these as a "blocked" list — the scanner flips is_valid=False when the
# answer is *about* any of them.
_BANNED_TOPICS: list[str] = [
    "politics",
    "violence",
    "religion",
    "adult content",
    "illegal activity",
    "medical advice",
    "financial advice",
    "legal advice",
]

_topic_scanner = BanTopics(topics=_BANNED_TOPICS)
# minimum_score is the entailment-probability bar an answer must clear vs. the
# concatenated retrieved context. Configurable via
# GUARDRAILS_FACTUALITY_MIN_SCORE (default 0.3, vs LLM Guard's upstream
# default 0.75). See src/config.py for the rationale on why 0.3 fits
# descriptive RAG prose.
#
# Lazy-init: live /query routes through src.guardrails.llm_judge for
# hallucination checks (NLI had a 40% FPR on grounded answers — see
# llm_judge/output_guards.py). This NLI variant is kept for the curriculum
# comparison module, but module import shouldn't pay the model load cost
# nor force the workspace image to pre-cache the underlying weights.
_factuality_scanner: FactualConsistency | None = None


def _get_factuality_scanner() -> FactualConsistency:
    global _factuality_scanner
    if _factuality_scanner is None:
        _factuality_scanner = FactualConsistency(
            minimum_score=settings.guardrails_factuality_min_score,
        )
    return _factuality_scanner


def check_hallucination(answer: str, sources: list[Source]) -> str | None:
    """Return a reason if the NLI classifier says the answer contradicts the sources."""
    if not sources:
        # No retrieval support; confidence score already surfaces this.
        return None
    reference = " ".join(s.chunk_text for s in sources)
    _sanitized, is_valid, risk_score = _get_factuality_scanner().scan(reference, answer)
    if not is_valid:
        return (
            f"hallucination: FactualConsistency entailment score below threshold "
            f"(risk={risk_score:.3f})"
        )
    return None


def is_off_topic(answer: str) -> str | None:
    """Return a reason if the answer is about one of the banned topics."""
    _sanitized, is_valid, risk_score = _topic_scanner.scan("", answer)
    if not is_valid:
        return f"off_topic: BanTopics flagged answer (risk={risk_score:.3f})"
    return None
