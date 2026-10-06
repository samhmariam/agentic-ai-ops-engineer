"""Tests for src.optimization.streaming."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.models import Source, TokenUsage
from src.optimization.streaming import (
    compare_ttft,
    measure_ttft_blocking,
    measure_ttft_streaming,
    stream_completion,
)


def _delta(text: str | None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
        usage=None,
    )


def _usage_chunk(prompt: int, completion: int):
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


def _source() -> Source:
    return Source(doc_id="p1", chunk_text="x", similarity_score=0.9)


# --- stream_completion ------------------------------------------------------


def test_stream_completion_yields_each_token_then_final_tuple():
    chunks = [
        _delta("Hello"),
        _delta(" world"),
        _delta("!"),
        _usage_chunk(prompt=10, completion=3),
    ]

    with patch("src.optimization.streaming._client") as client:
        client.chat.completions.create.return_value = iter(chunks)
        produced = list(stream_completion("Q", [_source()], "gpt-4o-mini"))

    assert produced[:-1] == ["Hello", " world", "!"]
    answer, usage, cost = produced[-1]
    assert answer == "Hello world!"
    assert usage == TokenUsage(prompt_tokens=10, completion_tokens=3)
    assert cost == pytest.approx((10 * 0.15 + 3 * 0.60) / 1_000_000)


def test_stream_completion_skips_empty_deltas():
    chunks = [
        _delta(None),
        _delta(""),
        _delta("only"),
        _usage_chunk(0, 1),
    ]

    with patch("src.optimization.streaming._client") as client:
        client.chat.completions.create.return_value = iter(chunks)
        produced = list(stream_completion("Q", [_source()], "gpt-4o-mini"))

    assert [p for p in produced if isinstance(p, str)] == ["only"]


def test_stream_completion_handles_missing_usage_chunk():
    chunks = [_delta("a"), _delta("b")]

    with patch("src.optimization.streaming._client") as client:
        client.chat.completions.create.return_value = iter(chunks)
        produced = list(stream_completion("Q", [_source()], "gpt-4o-mini"))

    answer, usage, cost = produced[-1]
    assert answer == "ab"
    assert usage == TokenUsage(prompt_tokens=0, completion_tokens=0)
    assert cost == 0.0


def test_stream_completion_passes_stream_options_to_openai():
    with patch("src.optimization.streaming._client") as client:
        client.chat.completions.create.return_value = iter([_usage_chunk(1, 1)])
        list(stream_completion("Q", [_source()], "gpt-4o-mini"))

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["model"] == "gpt-4o-mini"


# --- measure_ttft_streaming -------------------------------------------------


def test_measure_ttft_streaming_returns_expected_keys():
    chunks = [_delta("a"), _delta("b"), _usage_chunk(5, 2)]

    with patch("src.optimization.streaming.retrieve", return_value=[_source()]), \
         patch("src.optimization.streaming._client") as client:
        client.chat.completions.create.return_value = iter(chunks)
        result = measure_ttft_streaming("Q", model="gpt-4o-mini", top_k=2)

    assert set(result.keys()) == {"ttft_ms", "total_ms", "total_tokens"}
    assert result["ttft_ms"] >= 0
    assert result["total_ms"] >= result["ttft_ms"]
    assert result["total_tokens"] == 7  # 5 + 2


# --- measure_ttft_blocking --------------------------------------------------


def test_measure_ttft_blocking_uses_run_pipeline():
    from src.models import QueryResponse, TokenUsage as _TU

    fake = QueryResponse(
        answer="ans",
        sources=[_source()],
        confidence=0.9,
        model="gpt-4o-mini",
        tokens=_TU(prompt_tokens=5, completion_tokens=10),
        cost_usd=0.001,
    )

    with patch("src.optimization.streaming.run_pipeline", return_value=fake) as run:
        result = measure_ttft_blocking("Q", model="gpt-4o-mini", top_k=3)

    run.assert_called_once_with("Q", model="gpt-4o-mini", top_k=3)
    assert result["ttft_ms"] == result["total_ms"]
    assert result["total_tokens"] == 15


# --- compare_ttft -----------------------------------------------------------


def test_compare_ttft_combines_both_modes_with_improvement_metric():
    blocking_result = {"ttft_ms": 800.0, "total_ms": 800.0, "total_tokens": 50}
    streaming_result = {"ttft_ms": 200.0, "total_ms": 900.0, "total_tokens": 50}

    with patch(
        "src.optimization.streaming.measure_ttft_blocking", return_value=blocking_result
    ), patch(
        "src.optimization.streaming.measure_ttft_streaming", return_value=streaming_result
    ):
        result = compare_ttft("Q")

    assert result["blocking"] == blocking_result
    assert result["streaming"] == streaming_result
    assert result["ttft_improvement_ms"] == 600.0
    assert result["ttft_improvement_pct"] == pytest.approx(75.0)


def test_compare_ttft_handles_zero_blocking_time():
    with patch(
        "src.optimization.streaming.measure_ttft_blocking",
        return_value={"ttft_ms": 0.0, "total_ms": 0.0, "total_tokens": 0},
    ), patch(
        "src.optimization.streaming.measure_ttft_streaming",
        return_value={"ttft_ms": 0.0, "total_ms": 0.0, "total_tokens": 0},
    ):
        result = compare_ttft("Q")

    assert result["ttft_improvement_pct"] == 0.0


def test_package_init_does_not_eagerly_import_routes():
    """INSTRUCTIONS.md §11 documents `from src.optimization.streaming import
    compare_ttft` as the bonus-task invocation. Previously, src.optimization's
    package __init__ eagerly imported the FastAPI router, which triggered a
    circular import via src.gateway.app whenever a script invoked the rubric's
    example before the FastAPI app factory finished. Regression: prove the
    package init no longer pulls in `routes` (and therefore not the cycle).
    """
    import src.optimization as opt
    # The router should NOT be a package-level attribute.
    assert not hasattr(opt, "router"), (
        "src.optimization re-exporting `router` would re-introduce the "
        "circular import that breaks INSTRUCTIONS.md §11's documented "
        "`from src.optimization.streaming import compare_ttft` invocation."
    )
    # The streaming helpers SHOULD still be package-level (back-compat).
    assert hasattr(opt, "compare_ttft")
    assert hasattr(opt, "measure_ttft_blocking")
    assert hasattr(opt, "measure_ttft_streaming")
    assert hasattr(opt, "stream_completion")
