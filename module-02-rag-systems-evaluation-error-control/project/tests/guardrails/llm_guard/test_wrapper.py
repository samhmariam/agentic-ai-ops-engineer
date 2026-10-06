"""Tests for src.guardrails.llm_guard.wrapper.guarded_route_query_llmguard."""

from unittest.mock import patch

from src.guardrails import SAFE_BLOCKED_MESSAGE, SAFE_FILTERED_MESSAGE
from src.guardrails.llm_guard import guarded_route_query_llmguard
from src.models import QueryResponse, Source, TokenUsage


def _good_response() -> QueryResponse:
    return QueryResponse(
        answer="The Selkirk AMPED S2 weighs 7.8 oz.",
        sources=[Source(doc_id="p1", chunk_text="Selkirk AMPED S2 weighs 7.8 oz.", similarity_score=0.92)],
        confidence=0.92,
        model="gpt-4o-mini",
        tokens=TokenUsage(prompt_tokens=120, completion_tokens=18),
        cost_usd=0.0000288,
        trace_id="t-1",
    )


def test_input_injection_short_circuits():
    with patch(
        "src.guardrails.llm_guard.wrapper.detect_prompt_injection",
        return_value="prompt_injection: risk_score=0.980",
    ), patch("src.guardrails.llm_guard.wrapper.route_query") as route:
        result = guarded_route_query_llmguard("attacker text")

    route.assert_not_called()
    assert result.answer == SAFE_BLOCKED_MESSAGE
    assert result.blocked_by == "prompt_injection: risk_score=0.980"


def test_pii_input_is_redacted_then_forwarded_and_annotated():
    with patch(
        "src.guardrails.llm_guard.wrapper.detect_prompt_injection", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.detect_pii",
        return_value=("Email [REDACTED_EMAIL_ADDRESS_1] about weight", ["email_address"]),
    ), patch(
        "src.guardrails.llm_guard.wrapper.route_query", return_value=_good_response()
    ) as route, patch(
        "src.guardrails.llm_guard.wrapper.check_hallucination", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.is_off_topic", return_value=None
    ):
        result = guarded_route_query_llmguard("Email jane@x.com about weight")

    route.assert_called_once()
    cleaned = route.call_args.args[0]
    assert "jane@x.com" not in cleaned
    assert "[REDACTED_EMAIL_ADDRESS_1]" in cleaned

    assert result.answer.startswith("The Selkirk")
    assert result.blocked_by == "pii_redacted: email_address"


def test_clean_request_passes_through_unannotated():
    with patch(
        "src.guardrails.llm_guard.wrapper.detect_prompt_injection", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.detect_pii",
        return_value=("How heavy is the Selkirk?", []),
    ), patch(
        "src.guardrails.llm_guard.wrapper.route_query", return_value=_good_response()
    ), patch(
        "src.guardrails.llm_guard.wrapper.check_hallucination", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.is_off_topic", return_value=None
    ):
        result = guarded_route_query_llmguard("How heavy is the Selkirk?")

    assert result.answer.startswith("The Selkirk")
    assert result.blocked_by is None


def test_hallucinated_output_returns_filtered_safe_response():
    with patch(
        "src.guardrails.llm_guard.wrapper.detect_prompt_injection", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.detect_pii", return_value=("q", [])
    ), patch(
        "src.guardrails.llm_guard.wrapper.route_query", return_value=_good_response()
    ), patch(
        "src.guardrails.llm_guard.wrapper.check_hallucination",
        return_value="hallucination: entailment below threshold",
    ), patch(
        "src.guardrails.llm_guard.wrapper.is_off_topic", return_value=None
    ):
        result = guarded_route_query_llmguard("q")

    assert result.answer == SAFE_FILTERED_MESSAGE
    assert result.blocked_by == "hallucination: entailment below threshold"


def test_off_topic_output_returns_filtered_safe_response():
    with patch(
        "src.guardrails.llm_guard.wrapper.detect_prompt_injection", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.detect_pii", return_value=("q", [])
    ), patch(
        "src.guardrails.llm_guard.wrapper.route_query", return_value=_good_response()
    ), patch(
        "src.guardrails.llm_guard.wrapper.check_hallucination", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.is_off_topic",
        return_value="off_topic: BanTopics flagged answer",
    ):
        result = guarded_route_query_llmguard("q")

    assert result.answer == SAFE_FILTERED_MESSAGE
    assert result.blocked_by == "off_topic: BanTopics flagged answer"


def test_top_k_is_forwarded_to_route_query():
    with patch(
        "src.guardrails.llm_guard.wrapper.detect_prompt_injection", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.detect_pii", return_value=("q", [])
    ), patch(
        "src.guardrails.llm_guard.wrapper.route_query", return_value=_good_response()
    ) as route, patch(
        "src.guardrails.llm_guard.wrapper.check_hallucination", return_value=None
    ), patch(
        "src.guardrails.llm_guard.wrapper.is_off_topic", return_value=None
    ):
        guarded_route_query_llmguard("q", top_k=3)

    assert route.call_args.kwargs["top_k"] == 3
