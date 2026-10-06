"""Tests for src.guardrails.llm_judge.output_guards."""

import json
from unittest.mock import MagicMock, patch

from src.guardrails.llm_judge import check_hallucination
from src.models import Source


def _src(doc_id: str, text: str) -> Source:
    return Source(doc_id=doc_id, chunk_text=text, similarity_score=0.9)


def _fake_response(content: str, prompt_tokens: int = 50, completion_tokens: int = 20):
    """Build a mock that mirrors openai.types.ChatCompletion."""
    response = MagicMock()
    response.choices[0].message.content = content
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


def test_check_hallucination_no_sources_returns_none_without_calling_openai():
    with patch("src.guardrails.llm_judge.output_guards._client") as client, \
         patch("src.guardrails.llm_judge.output_guards.log_request") as logger:
        result = check_hallucination("any answer", [])

    assert result is None
    client.chat.completions.create.assert_not_called()
    logger.assert_not_called()


def test_check_hallucination_passes_when_judge_returns_supported():
    sources = [_src("p1", "The Selkirk AMPED S2 weighs 7.8 oz.")]
    payload = json.dumps({"verdict": "SUPPORTED", "reason": "weight matches source"})
    with patch("src.guardrails.llm_judge.output_guards._client") as client, \
         patch("src.guardrails.llm_judge.output_guards.log_request") as logger:
        client.chat.completions.create.return_value = _fake_response(payload)
        result = check_hallucination("The Selkirk weighs 7.8 oz.", sources)

    assert result is None
    client.chat.completions.create.assert_called_once()
    # Cost is logged once when the judge runs
    logger.assert_called_once()
    log_args = logger.call_args.args
    assert log_args[0] == "gpt-4o-mini"  # settings.model_simple default
    assert log_args[3] == "hallucination_check"


def test_check_hallucination_blocks_when_judge_returns_not_supported():
    sources = [_src("p1", "The Selkirk AMPED S2 weighs 7.8 oz.")]
    payload = json.dumps(
        {"verdict": "NOT_SUPPORTED", "reason": "answer claims 12 oz; source says 7.8 oz"}
    )
    with patch("src.guardrails.llm_judge.output_guards._client") as client, \
         patch("src.guardrails.llm_judge.output_guards.log_request"):
        client.chat.completions.create.return_value = _fake_response(payload)
        result = check_hallucination("The Selkirk weighs 12 oz.", sources)

    assert result is not None
    assert result.startswith("hallucination:")
    assert "12 oz" in result


def test_check_hallucination_fails_open_on_malformed_json():
    sources = [_src("p1", "x")]
    with patch("src.guardrails.llm_judge.output_guards._client") as client, \
         patch("src.guardrails.llm_judge.output_guards.log_request") as logger, \
         patch("src.guardrails.llm_judge.output_guards.LOGGER") as scanner_logger:
        client.chat.completions.create.return_value = _fake_response("not json at all")
        result = check_hallucination("any", sources)

    assert result is None
    # Cost not logged on parse error — the return-early branch sits above the log call
    logger.assert_not_called()
    scanner_logger.warning.assert_called_once()


def test_check_hallucination_fails_open_on_missing_verdict_field():
    sources = [_src("p1", "x")]
    payload = json.dumps({"reason": "no verdict key here"})
    with patch("src.guardrails.llm_judge.output_guards._client") as client, \
         patch("src.guardrails.llm_judge.output_guards.log_request") as logger, \
         patch("src.guardrails.llm_judge.output_guards.LOGGER") as scanner_logger:
        client.chat.completions.create.return_value = _fake_response(payload)
        result = check_hallucination("any", sources)

    assert result is None
    logger.assert_not_called()
    scanner_logger.warning.assert_called_once()


def test_check_hallucination_fails_open_on_openai_exception():
    sources = [_src("p1", "x")]
    with patch("src.guardrails.llm_judge.output_guards._client") as client, \
         patch("src.guardrails.llm_judge.output_guards.log_request") as logger, \
         patch("src.guardrails.llm_judge.output_guards.LOGGER") as scanner_logger:
        client.chat.completions.create.side_effect = RuntimeError("network down")
        result = check_hallucination("any", sources)

    assert result is None
    logger.assert_not_called()
    scanner_logger.warning.assert_called_once()
