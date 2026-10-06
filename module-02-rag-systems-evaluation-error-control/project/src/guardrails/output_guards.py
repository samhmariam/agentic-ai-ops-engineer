"""Output-side validators: hallucination + off-topic.

Heuristic implementations sized for the capstone. The teaching point is
*what* to check; the implementation can be replaced with an LLM judge or
an embedding-similarity check in production.

To add a new on-topic keyword, append it to ``_ON_TOPIC_KEYWORDS``.
To loosen or tighten the proper-noun match for hallucination detection,
edit ``_PROPER_NOUN_PATTERN``. The HTTP route in ``src.gateway.routes``
runs these functions after ``route_query`` — a flagged response never
enters the cache.
"""

import re
from typing import Iterable

from src.models import Source

# Multi-word capitalised phrases (likely product/brand names) that the
# answer might claim and that we then check against the retrieved sources.
_PROPER_NOUN_PATTERN = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9]*)(?:\s+[A-Z][a-zA-Z0-9]*){1,4}\b"
)

# Articles/determiners that get glued to a product name when it appears
# at the start of a sentence. Strip these so "The Selkirk AMPED S2" is
# checked as "Selkirk AMPED S2".
_LEADING_DETERMINERS: tuple[str, ...] = ("the", "a", "an", "our", "my", "your", "their")

# Tokens that mark on-topic answers for ThirdShotHub product Q&A.
_ON_TOPIC_KEYWORDS: set[str] = {
    "thirdshothub",
    "paddle",
    "paddles",
    "court",
    "ball",
    "balls",
    "selkirk",
    "joola",
    "amped",
    "hyperion",
    "weight",
    "grip",
    "core",
    "face",
    "polypropylene",
    "fiberflex",
}

# Phrases the assistant uses when it correctly refuses to answer.
_REFUSAL_PHRASES: tuple[str, ...] = (
    "i don't have",
    "i do not have",
    "based on the products in our catalog",
    "i can't help with that",
    "i cannot help with that",
    "i don't know",
)


def _normalize(text: str) -> str:
    return text.lower()


def _source_text(sources: Iterable[Source]) -> str:
    return _normalize(" ".join(s.chunk_text for s in sources))


def check_hallucination(answer: str, sources: list[Source]) -> str | None:
    """Return a reason if the answer mentions a proper noun absent from any source."""
    if not sources:
        # No retrieval support means nothing to verify against — handled elsewhere
        # via the confidence score; not the hallucination guard's concern.
        return None

    haystack = _source_text(sources)
    for phrase in _PROPER_NOUN_PATTERN.findall(answer):
        words = phrase.split()
        if words and words[0].lower() in _LEADING_DETERMINERS:
            words = words[1:]
        if not words:
            continue
        check = " ".join(words).lower()
        if check not in haystack:
            return f"hallucination: '{' '.join(words)}' not present in any retrieved source"
    return None


def is_off_topic(answer: str) -> str | None:
    """Return a reason if the answer is neither on-topic nor a clear refusal."""
    lower = _normalize(answer)
    if any(phrase in lower for phrase in _REFUSAL_PHRASES):
        return None
    tokens = set(re.findall(r"[a-z][a-z0-9]+", lower))
    if tokens & _ON_TOPIC_KEYWORDS:
        return None
    return "off_topic: answer does not reference any ThirdShotHub product domain term"
