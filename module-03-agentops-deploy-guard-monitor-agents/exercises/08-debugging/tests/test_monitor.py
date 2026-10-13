import json
import tempfile
from pathlib import Path

import pytest

from realthor.monitor import (
    MonitoringMetrics,
    RunRecord,
    compute_metrics,
    generate_report,
    load_run_records,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_run_records_returns_empty_when_no_file(tmp_path):
    records = load_run_records(tmp_path / "nonexistent.jsonl")
    assert records == []


def test_load_run_records_parses_single_record(tmp_path):
    record = {
        "run_id": "r1", "timestamp": "2026-06-01T09:00:00+00:00",
        "user_id": "u1", "command": "chat", "input_text": "hello",
        "success": True, "failure_reason": "", "latency_s": 1.5,
        "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.00005,
        "tools_called": ["tool_a"], "guardrail_blocked": False,
        "guardrail_reason": "", "hitl_decision": "none",
    }
    log = tmp_path / "runs.jsonl"
    log.write_text(json.dumps(record) + "\n")
    records = load_run_records(log)
    assert len(records) == 1
    assert records[0].run_id == "r1"
    assert records[0].tools_called == ["tool_a"]


def test_load_run_records_parses_multiple_records():
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    assert len(records) == 10
    assert all(isinstance(r, RunRecord) for r in records)


def test_compute_metrics_counts_and_rate():
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    metrics = compute_metrics(records)
    assert metrics.total_runs == 10
    assert metrics.success_count == 8
    assert metrics.failure_count == 2
    assert abs(metrics.success_rate - 0.8) < 1e-9


def test_compute_metrics_avg_latency():
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    metrics = compute_metrics(records)
    expected = sum(r.latency_s for r in records) / len(records)
    assert abs(metrics.avg_latency_s - expected) < 1e-9


def test_compute_metrics_p95_latency():
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    metrics = compute_metrics(records)
    # fewer than 20 records → p95 fallback is max latency
    expected_p95 = max(r.latency_s for r in records)
    assert abs(metrics.p95_latency_s - expected_p95) < 1e-9


def test_compute_metrics_cost_totals():
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    metrics = compute_metrics(records)
    expected_total = sum(r.cost_usd for r in records)
    assert abs(metrics.total_cost_usd - expected_total) < 1e-9
    assert abs(metrics.avg_cost_usd - expected_total / len(records)) < 1e-9


def test_compute_metrics_tool_call_counts():
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    metrics = compute_metrics(records)
    assert metrics.tool_call_counts.get("get_listing_velocity", 0) >= 2
    assert metrics.tool_call_counts.get("get_supply_snapshot", 0) >= 1
    assert metrics.guardrail_block_count == 1
    assert metrics.hitl_approval_count == 1
    assert metrics.hitl_rejection_count == 1


def test_generate_report_creates_output_files(tmp_path):
    records = load_run_records(FIXTURES / "sample_runs.jsonl")
    metrics = compute_metrics(records)
    generate_report(metrics, tmp_path)
    md_path = tmp_path / "monitoring_report.md"
    json_path = tmp_path / "monitoring_report.json"
    html_path = tmp_path / "monitoring_report.html"
    assert md_path.exists()
    assert json_path.exists()
    assert html_path.exists()
    md = md_path.read_text()
    assert "Total runs" in md
    assert "Success rate" in md
    data = json.loads(json_path.read_text())
    assert data["total_runs"] == 10
    assert "tool_call_counts" in data
    html = html_path.read_text()
    assert "RealThor Monitoring Report" in html
    assert "10" in html
