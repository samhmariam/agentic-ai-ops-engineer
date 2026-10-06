"""Tests for src.guardrails.output_guards."""

import pytest

from src.guardrails import check_hallucination, is_off_topic
from src.models import Source


def _src(doc_id: str, text: str) -> Source:
    return Source(doc_id=doc_id, chunk_text=text, similarity_score=0.9)


def test_check_hallucination_passes_when_proper_nouns_in_sources():
    sources = [_src("p1", "The Selkirk AMPED S2 weighs 7.8 oz.")]
    assert check_hallucination("The Selkirk AMPED S2 is light at 7.8 oz.", sources) is None


def test_check_hallucination_flags_invented_product_name():
    sources = [_src("p1", "The Selkirk AMPED S2 weighs 7.8 oz.")]
    answer = "The Babolat Pure Drive is the lightest paddle we offer."
    reason = check_hallucination(answer, sources)
    assert reason is not None
    assert "Babolat Pure Drive" in reason


def test_check_hallucination_no_sources_returns_none():
    # No sources is the retriever's problem, not the hallucination guard's.
    assert check_hallucination("Some answer", []) is None


def test_check_hallucination_passes_answer_with_no_proper_nouns():
    sources = [_src("p1", "Paddles weigh between 7 and 9 ounces.")]
    answer = "Paddles typically weigh between seven and nine ounces."
    assert check_hallucination(answer, sources) is None


def test_is_off_topic_passes_on_topic_answer():
    assert is_off_topic("The Selkirk paddle has a polypropylene core.") is None


def test_is_off_topic_passes_clean_refusal():
    assert is_off_topic("Based on the products in our catalog, I don't have that info.") is None
    assert is_off_topic("I don't know.") is None


@pytest.mark.parametrize(
    "answer",
    [
        "The capital of France is Paris.",
        "Quantum mechanics is fascinating.",
        "Buy our competitor's products instead.",
    ],
)
def test_is_off_topic_flags_unrelated_answers(answer):
    assert is_off_topic(answer) is not None
