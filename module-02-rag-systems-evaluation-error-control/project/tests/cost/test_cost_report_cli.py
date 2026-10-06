"""Tests for scripts/cost_report.py."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def cli_module():
    spec = importlib.util.spec_from_file_location(
        "_cost_report_cli",
        Path(__file__).resolve().parents[2] / "scripts" / "cost_report.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cost_log(tmp_path):
    """Write a small JSONL log: 2 simple (mini) + 1 complex (4o)."""
    path = tmp_path / "cost.jsonl"
    rows = [
        # gpt-4o-mini: 1000 in + 200 out = (1000*0.15 + 200*0.60)/1M = $0.000270
        {"model": "gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 200, "cost_usd": 0.000270, "query_type": "simple", "timestamp": "t"},
        {"model": "gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 200, "cost_usd": 0.000270, "query_type": "simple", "timestamp": "t"},
        # gpt-4o: 1000 in + 200 out = (1000*2.50 + 200*10.00)/1M = $0.004500
        {"model": "gpt-4o", "prompt_tokens": 1000, "completion_tokens": 200, "cost_usd": 0.004500, "query_type": "complex", "timestamp": "t"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_baseline_cost_recomputes_at_target_model(cli_module):
    records = [
        {"model": "gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 200, "cost_usd": 0.000270},
    ]
    # If this 1000+200 token call had hit gpt-4o instead:
    expected = (1000 * 2.50 + 200 * 10.00) / 1_000_000  # = 0.0045
    assert cli_module.baseline_cost(records, "gpt-4o") == pytest.approx(expected)


def test_cli_reports_savings_vs_baseline(cli_module, cost_log, capsys):
    exit_code = cli_module.main(["--log", str(cost_log)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Records:           3" in out
    # Actual: 2 * 0.000270 + 1 * 0.004500 = 0.005040
    assert "Actual cost:       $0.0050" in out
    # Baseline: 3 * 0.004500 = 0.013500
    assert "Baseline (gpt-4o): $0.0135" in out
    # Savings: 0.013500 - 0.005040 = 0.008460, % = 0.00846/0.0135 * 100 = 62.67%
    assert "Savings:           $0.0085" in out
    assert "62.7%" in out


def test_cli_handles_empty_log(cli_module, tmp_path, capsys):
    exit_code = cli_module.main(["--log", str(tmp_path / "missing.jsonl")])
    assert exit_code == 0
    assert "No records in cost log" in capsys.readouterr().out


def test_cli_prints_per_tier_summary(cli_module, cost_log, capsys):
    cli_module.main(["--log", str(cost_log)])

    out = capsys.readouterr().out
    assert "Per-tier summary:" in out
    # gpt-4o dominates total spend (1 × $0.0045 = $0.0045) and should
    # print first; gpt-4o-mini follows (2 × $0.000270 = $0.000540).
    gpt4o_idx = out.index("gpt-4o ")
    mini_idx = out.index("gpt-4o-mini")
    assert gpt4o_idx < mini_idx
    # Counts + per-query averages appear verbatim in the per-tier block.
    assert "N=   1" in out
    assert "N=   2" in out
    assert "avg=$0.0045/query" in out
    assert "avg=$0.0003/query" in out
