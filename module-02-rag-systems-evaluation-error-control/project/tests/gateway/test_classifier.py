"""Tests for src.gateway.classifier."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.gateway import classify


def _completion(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_classify_returns_simple_for_simple_label():
    with patch("src.gateway.classifier._client") as client:
        client.chat.completions.create.return_value = _completion(
            '{"classification": "simple", "reasoning": "factual lookup"}'
        )

        result = classify("How much does the Selkirk weigh?")

    assert result == "simple"


def test_classify_returns_complex_for_complex_label():
    with patch("src.gateway.classifier._client") as client:
        client.chat.completions.create.return_value = _completion(
            '{"classification": "complex", "reasoning": "comparison"}'
        )

        result = classify("Which paddle is best for an intermediate player?")

    assert result == "complex"


def test_classify_uses_simple_model_and_renders_query_into_prompt():
    with patch("src.gateway.classifier._client") as client:
        client.chat.completions.create.return_value = _completion(
            '{"classification": "simple", "reasoning": "x"}'
        )

        classify("How heavy is the Joola?")

    call = client.chat.completions.create.call_args.kwargs
    assert call["model"] == "gpt-4o-mini"
    assert call["response_format"] == {"type": "json_object"}
    assert "How heavy is the Joola?" in call["messages"][0]["content"]


@pytest.mark.parametrize(
    "bad_content",
    [
        "this is not json",
        '{"classification": "neither"}',
        "{}",
        '{"classification": null}',
    ],
)
def test_classify_falls_back_to_complex_on_bad_response(bad_content):
    with patch("src.gateway.classifier._client") as client:
        client.chat.completions.create.return_value = _completion(bad_content)

        assert classify("anything") == "complex"


def test_classify_handles_empty_completion_content():
    with patch("src.gateway.classifier._client") as client:
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )

        assert classify("anything") == "complex"
