"""Tests for src.cost.tracker."""

import json

import pytest

from src.cost.tracker import load_log, log_request, summarize
from src.models import TokenUsage


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "cost.jsonl"


def test_log_request_appends_jsonl_record(log_path):
    record = log_request(
        model="gpt-4o-mini",
        usage=TokenUsage(prompt_tokens=120, completion_tokens=18),
        cost_usd=0.0000288,
        query_type="simple",
        path=log_path,
    )

    assert record["model"] == "gpt-4o-mini"
    assert record["prompt_tokens"] == 120
    assert record["completion_tokens"] == 18
    assert record["cost_usd"] == 0.0000288
    assert record["query_type"] == "simple"
    assert "timestamp" in record

    contents = log_path.read_text().strip().split("\n")
    assert len(contents) == 1
    assert json.loads(contents[0]) == record


def test_log_request_appends_multiple_records(log_path):
    log_request(
        "gpt-4o-mini",
        TokenUsage(prompt_tokens=100, completion_tokens=10),
        0.0000060,
        "simple",
        path=log_path,
    )
    log_request(
        "gpt-4o",
        TokenUsage(prompt_tokens=200, completion_tokens=50),
        0.0010000,
        "complex",
        path=log_path,
    )

    records = load_log(log_path)
    assert len(records) == 2
    assert records[0]["model"] == "gpt-4o-mini"
    assert records[1]["model"] == "gpt-4o"


def test_log_request_creates_parent_directory(tmp_path):
    nested = tmp_path / "deeply" / "nested" / "cost.jsonl"

    log_request(
        "gpt-4o",
        TokenUsage(prompt_tokens=10, completion_tokens=5),
        0.0001,
        "complex",
        path=nested,
    )

    assert nested.exists()
    assert len(load_log(nested)) == 1


def test_load_log_returns_empty_list_when_missing(tmp_path):
    assert load_log(tmp_path / "missing.jsonl") == []


def test_summarize_aggregates_totals_and_per_model_breakdown():
    records = [
        {"model": "gpt-4o-mini", "cost_usd": 0.001, "prompt_tokens": 1, "completion_tokens": 1},
        {"model": "gpt-4o-mini", "cost_usd": 0.002, "prompt_tokens": 1, "completion_tokens": 1},
        {"model": "gpt-4o", "cost_usd": 0.010, "prompt_tokens": 1, "completion_tokens": 1},
    ]

    summary = summarize(records)

    assert summary["total_requests"] == 3
    assert summary["total_cost_usd"] == pytest.approx(0.013)
    assert summary["by_model"]["gpt-4o-mini"] == {
        "requests": 2,
        "cost_usd": pytest.approx(0.003),
        "avg_cost_usd": pytest.approx(0.0015),
    }
    assert summary["by_model"]["gpt-4o"] == {
        "requests": 1,
        "cost_usd": pytest.approx(0.010),
        "avg_cost_usd": pytest.approx(0.010),
    }


def test_summarize_handles_empty_records():
    summary = summarize([])
    assert summary == {"total_requests": 0, "total_cost_usd": 0.0, "by_model": {}}
