"""Tests for src.rag.generator."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.models import Source, TokenUsage
from src.rag import generate
from src.rag.generator import compute_cost, render_system_prompt


@pytest.fixture
def fake_sources() -> list[Source]:
    return [
        Source(doc_id="p1", chunk_text="Selkirk AMPED S2 weighs 7.8 oz.", similarity_score=0.91),
        Source(doc_id="p2", chunk_text="Joola Hyperion CFS 16mm paddle.", similarity_score=0.84),
    ]


def test_render_system_prompt_includes_each_source(fake_sources):
    rendered = render_system_prompt(fake_sources)

    assert "ThirdShotHub" in rendered  # template content survives
    assert "[p1] Selkirk AMPED S2 weighs 7.8 oz." in rendered
    assert "[p2] Joola Hyperion CFS 16mm paddle." in rendered


def test_compute_cost_uses_per_million_pricing():
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000)

    cost_4o = compute_cost("gpt-4o", usage)
    cost_mini = compute_cost("gpt-4o-mini", usage)

    # gpt-4o: 1M * $2.50 + 0.5M * $10.00 = $2.50 + $5.00 = $7.50
    assert cost_4o == pytest.approx(7.50)
    # gpt-4o-mini: 1M * $0.15 + 0.5M * $0.60 = $0.15 + $0.30 = $0.45
    assert cost_mini == pytest.approx(0.45)


def test_compute_cost_unknown_model_raises():
    with pytest.raises(KeyError):
        compute_cost("unknown-model", TokenUsage(prompt_tokens=1, completion_tokens=1))


def test_generate_calls_openai_and_returns_answer_usage_cost(fake_sources):
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Selkirk weighs 7.8 oz."))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=18),
    )

    with patch("src.rag.generator._client") as client:
        client.chat.completions.create.return_value = fake_response

        answer, usage, cost = generate(
            "How much does the Selkirk weigh?", fake_sources, model="gpt-4o-mini"
        )

    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["messages"][0]["role"] == "system"
    assert "ThirdShotHub" in call_kwargs["messages"][0]["content"]
    assert call_kwargs["messages"][1] == {
        "role": "user",
        "content": "How much does the Selkirk weigh?",
    }

    assert answer == "Selkirk weighs 7.8 oz."
    assert usage == TokenUsage(prompt_tokens=120, completion_tokens=18)
    # gpt-4o-mini: (120 * 0.15 + 18 * 0.60) / 1_000_000
    assert cost == pytest.approx((120 * 0.15 + 18 * 0.60) / 1_000_000)


def test_generate_handles_empty_completion(fake_sources):
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0),
    )

    with patch("src.rag.generator._client") as client:
        client.chat.completions.create.return_value = fake_response

        answer, _, _ = generate("Q", fake_sources, model="gpt-4o")

    assert answer == ""
