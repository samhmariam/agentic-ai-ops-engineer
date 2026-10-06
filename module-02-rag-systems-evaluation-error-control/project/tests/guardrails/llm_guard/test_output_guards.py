"""Tests for src.guardrails.llm_guard.output_guards."""

from unittest.mock import patch

from src.guardrails.llm_guard import check_hallucination, is_off_topic
from src.models import Source


def _src(doc_id: str, text: str) -> Source:
    return Source(doc_id=doc_id, chunk_text=text, similarity_score=0.9)


def test_check_hallucination_no_sources_returns_none():
    assert check_hallucination("any answer", []) is None


def test_check_hallucination_passes_when_factuality_valid():
    sources = [_src("p1", "The Selkirk AMPED S2 weighs 7.8 oz.")]
    with patch("src.guardrails.llm_guard.output_guards._factuality_scanner") as scanner:
        scanner.scan.return_value = ("The Selkirk weighs 7.8 oz.", True, 0.1)
        assert check_hallucination("The Selkirk weighs 7.8 oz.", sources) is None

    # reference text built from the source chunks is what's passed as `prompt`
    call_args = scanner.scan.call_args.args
    assert call_args[0] == "The Selkirk AMPED S2 weighs 7.8 oz."  # reference
    assert call_args[1] == "The Selkirk weighs 7.8 oz."  # output


def test_check_hallucination_flags_when_factuality_invalid():
    sources = [_src("p1", "Selkirk weighs 7.8 oz.")]
    with patch("src.guardrails.llm_guard.output_guards._factuality_scanner") as scanner:
        scanner.scan.return_value = ("Babolat is lighter.", False, 0.92)
        reason = check_hallucination("Babolat is lighter.", sources)

    assert reason is not None
    assert reason.startswith("hallucination:")
    assert "0.92" in reason


def test_check_hallucination_concatenates_multiple_sources():
    sources = [
        _src("p1", "Selkirk weighs 7.8 oz."),
        _src("p2", "Joola has a polypropylene core."),
    ]
    with patch("src.guardrails.llm_guard.output_guards._factuality_scanner") as scanner:
        scanner.scan.return_value = ("x", True, 0.0)
        check_hallucination("x", sources)

    reference = scanner.scan.call_args.args[0]
    assert "Selkirk weighs 7.8 oz." in reference
    assert "Joola has a polypropylene core." in reference


def test_is_off_topic_passes_when_topic_scanner_valid():
    with patch("src.guardrails.llm_guard.output_guards._topic_scanner") as scanner:
        scanner.scan.return_value = ("answer", True, 0.1)
        assert is_off_topic("answer") is None

    # BanTopics expects (prompt, output); we pass empty prompt
    assert scanner.scan.call_args.args == ("", "answer")


def test_is_off_topic_flags_when_topic_scanner_invalid():
    with patch("src.guardrails.llm_guard.output_guards._topic_scanner") as scanner:
        scanner.scan.return_value = ("answer", False, 0.85)
        reason = is_off_topic("Let's talk about politics instead.")

    assert reason is not None
    assert reason.startswith("off_topic:")
    assert "0.85" in reason
