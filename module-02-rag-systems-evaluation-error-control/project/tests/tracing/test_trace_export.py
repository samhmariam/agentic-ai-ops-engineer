"""Tests for src.tracing.trace_export rendering helpers."""

import json

import pandas as pd

from src.tracing.trace_export import (
    render_json,
    render_markdown,
    summarize_traces,
)


def _two_span_trace(trace_id: str = "trace_a") -> pd.DataFrame:
    """Build a synthetic Phoenix span DataFrame: one root + one child.

    Mirrors the column shape Phoenix actually emits — nested span
    attributes under ``rag.*`` flatten into a single dict-valued
    column ``attributes.rag``, not into per-key flat columns. Token
    counts live on the ``rag_generation`` child span, not the root.
    """
    return pd.DataFrame(
        [
            {
                "context.trace_id": trace_id,
                "name": "rag_query",
                "parent_id": None,
                "start_time": pd.Timestamp("2026-04-29 12:00:00"),
                "end_time": pd.Timestamp("2026-04-29 12:00:01"),
                "attributes.input.value": "How heavy is the Selkirk?",
                "attributes.rag": {
                    "model": "gpt-4o-mini",
                    "latency_ms": 850.0,
                },
                "attributes.llm.token_count.prompt": None,
                "attributes.llm.token_count.completion": None,
            },
            {
                "context.trace_id": trace_id,
                "name": "rag_generation",
                "parent_id": "root",
                "start_time": pd.Timestamp("2026-04-29 12:00:00.100"),
                "end_time": pd.Timestamp("2026-04-29 12:00:00.900"),
                "attributes.input.value": None,
                "attributes.rag": None,
                "attributes.llm.token_count.prompt": 120,
                "attributes.llm.token_count.completion": 30,
            },
        ]
    )


# --- summarize_traces -------------------------------------------------------


def test_summarize_traces_groups_by_trace_id():
    df = _two_span_trace()
    summaries = summarize_traces(df, last_n=10)

    assert len(summaries) == 1
    s = summaries[0]
    assert s["trace_id"] == "trace_a"[:8]
    assert "How heavy" in s["question"]
    assert s["model"] == "gpt-4o-mini"
    assert s["latency_ms"] == 850.0
    assert s["prompt_tokens"] == 120
    assert s["completion_tokens"] == 30


def test_summarize_traces_identifies_slowest_child():
    df = _two_span_trace()
    summaries = summarize_traces(df, last_n=10)

    s = summaries[0]
    assert s["slowest_span"] == "rag_generation"
    # 0.1s start, 0.9s end → 800ms
    assert s["slowest_ms"] == 800.0


def test_summarize_traces_handles_empty_df():
    summaries = summarize_traces(pd.DataFrame(), last_n=10)
    assert summaries == []


def test_summarize_traces_returns_at_most_last_n():
    rows = []
    for i in range(15):
        rows.extend(
            _two_span_trace(trace_id=f"trace_{i:02d}").to_dict("records")
        )
    df = pd.DataFrame(rows)

    summaries = summarize_traces(df, last_n=5)
    assert len(summaries) == 5


def test_summarize_traces_skips_traces_with_no_root():
    """A trace that only contains child spans is silently skipped."""
    df = pd.DataFrame(
        [
            {
                "context.trace_id": "orphan",
                "name": "rag_generation",  # no rag_query parent
                "parent_id": "missing_root",
                "start_time": pd.Timestamp("2026-04-29 12:00:00"),
                "end_time": pd.Timestamp("2026-04-29 12:00:01"),
                "attributes.input.value": None,
                "attributes.rag": None,
                "attributes.llm.token_count.prompt": None,
                "attributes.llm.token_count.completion": None,
            }
        ]
    )
    summaries = summarize_traces(df, last_n=10)
    assert summaries == []


# --- render_markdown --------------------------------------------------------


def test_render_markdown_with_traces():
    summaries = [
        {
            "trace_id": "abcd1234",
            "question": "test q",
            "model": "gpt-4o-mini",
            "latency_ms": 100.0,
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "slowest_span": "rag_generation",
            "slowest_ms": 80.0,
            "start_time": "2026-04-29",
        }
    ]
    output = render_markdown(summaries, total=1)

    assert "# Phoenix Trace Export" in output
    assert "1 trace(s) captured" in output
    assert "abcd1234" in output
    assert "test q" in output
    assert "gpt-4o-mini" in output
    assert "rag_generation" in output


def test_render_markdown_empty():
    output = render_markdown([], total=0)
    assert "No traces found" in output


# --- render_json ------------------------------------------------------------


def test_render_json_roundtrips():
    summaries = [
        {"trace_id": "abc", "question": "q", "latency_ms": 100.0},
    ]
    parsed = json.loads(render_json(summaries))
    assert parsed == summaries
