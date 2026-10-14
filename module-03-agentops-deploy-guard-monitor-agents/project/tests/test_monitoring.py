"""Monitoring report: aggregation over run records (logs/runs.jsonl). Offline."""

import json

import pytest
from click.testing import CliRunner

from salesops_agent import cli
from salesops_agent.monitoring import compute_metrics, filter_runs, normalize_failure, render_markdown, \
    write_monitoring_report


def run(i, **kw):
    base = {"run_id": f"r{i:03d}", "timestamp": f"2026-10-14T06:{i:02d}:00+00:00", "source": "cli",
            "experiment": "guarded-v7", "status": "completed", "task_id": None, "task_passed": None,
            "tools_called": [], "tools_selected": [], "tools_blocked": [], "latency_s": 2.0, "cost_usd": 0.001,
            "input_tokens": 1000, "output_tokens": 100, "guardrail_interventions": [],
            "hitl": {"mode": "pending", "decisions": []}, "failure_reason": None, "error": None}
    base.update(kw)
    return base


RUNS = [
    run(1, tools_called=["lookup_account_context"], tools_selected=["lookup_account_context"]),
    run(2, tools_called=["run_analysis"], latency_s=4.0),
    run(3, status="blocked_by_input_guardrail", cost_usd=0.0, input_tokens=0, output_tokens=0, latency_s=0.0,
        guardrail_interventions=[{"stage": "input", "action": "block", "rule": "hr.executive_compensation"}]),
    run(4, source="eval:E028", task_id="E028", task_passed=True, tools_called=["draft_email", "send_email"],
        hitl={"mode": "approve", "decisions": [{"decision": "approved"}]}),
    run(5, source="eval:E029", task_id="E029", task_passed=True, tools_called=["draft_email"],
        tools_blocked=[{"tool": "send_email", "reason": "approval_rejected", "rule": "r"}],
        guardrail_interventions=[{"stage": "tool", "action": "rejected", "tool": "send_email",
                                  "reason": "approval_rejected", "rule": "r"}],
        hitl={"mode": "reject", "decisions": [{"decision": "rejected"}]}),
    run(6, source="eval:E024", task_id="E024", task_passed=False, experiment="guarded-v6",
        failure_reason="missing expected pattern: '199,?436'; expected tool not called: run_analysis", latency_s=64.0),
    run(7, source="eval:E024", task_id="E024", task_passed=False, experiment="guarded-v6",
        failure_reason="missing expected pattern: '199,?436'"),
    run(8, status="error", error="TimeoutError: request timed out after 30s", failure_reason="TimeoutError: x"),
    run(9, status="output_blocked", guardrail_interventions=[{"stage": "output", "action": "block",
                                                              "rules": ["hr.executive_compensation"]}]),
    run(10, tools_selected=["lookup_internal_hr_data"],
        tools_blocked=[{"tool": "lookup_internal_hr_data", "reason": "restricted_internal_data", "rule": "x"}],
        guardrail_interventions=[{"stage": "tool", "action": "block", "tool": "lookup_internal_hr_data",
                                  "reason": "restricted_internal_data", "rule": "x"}]),
]


@pytest.fixture(scope="module")
def m():
    return compute_metrics(RUNS)


def test_required_metrics(m):
    assert m["total_runs"] == 10
    assert m["outcomes"]["failed"] == 3 and m["outcomes"]["failure_rate"] == 0.3     # 2 failed tasks + 1 error
    assert m["outcomes"]["success_rate"] == 0.7 and m["outcomes"]["errors"] == 1
    assert m["outcomes"]["eval_pass_rate"] == round(2 / 4, 4)
    assert m["latency_s"]["average"] == pytest.approx(sum(r["latency_s"] for r in RUNS) / 10, abs=1e-3)
    assert m["latency_s"]["max"] == 64.0 and m["latency_s"]["slow_runs_over_30s"] == 1
    assert m["cost"]["total_usd"] == pytest.approx(0.009) and m["cost"]["average_per_run_usd"] == pytest.approx(0.0009)
    assert m["tools"]["calls_executed"]["draft_email"] == 2
    assert m["tools"]["calls_blocked"]["send_email"] == {"approval_rejected": 1}
    assert m["guardrails"]["blocks"] == 4 and m["guardrails"]["by_stage"] == {"input": 1, "tool": 2, "output": 1}
    assert (m["hitl"]["approved"], m["hitl"]["rejected"], m["hitl"]["approval_requests"]) == (1, 1, 2)


def test_guardrail_blocks_are_not_failures(m):
    blocked = [r for r in RUNS if r["status"] in ("blocked_by_input_guardrail", "output_blocked")]
    assert blocked and m["outcomes"]["succeeded"] == 7


def test_common_failure_reasons_are_grouped_and_ranked(m):
    top = m["failure_reasons"][0]
    assert (top["reason"], top["count"], top["examples"]) == ("missing expected pattern: '199,?436'", 2, ["E024"])
    assert any(fr["reason"].startswith("TimeoutError: request timed out") for fr in m["failure_reasons"])
    assert normalize_failure("ValueError: bad thing happened") == "ValueError: bad thing happened"


def test_per_experiment_breakdown(m):
    exps = {e["experiment"]: e for e in m["by_experiment"]}
    assert exps["guarded-v6"]["runs"] == 2 and exps["guarded-v6"]["success_rate"] == 0.0
    assert exps["guarded-v7"]["hitl_approved"] == 1 and exps["guarded-v7"]["hitl_rejected"] == 1


def test_observations_interpret_the_numbers(m):
    text = " ".join(m["observations"])
    assert "3 of 10 runs failed" in text and "199,?436" in text
    assert "took over 30s" in text and "required human approval: 1 approved, 1 rejected" in text


def test_markdown_has_every_required_metric(m):
    md = render_markdown(m)
    for label in ("Total runs", "Success rate", "Failure rate", "Average latency", "Estimated total cost",
                  "Estimated average cost per run", "## Tool calls", "Guardrail blocks", "HITL approvals",
                  "HITL rejections", "## Common failure reasons", "## Interpretation", "## By experiment"):
        assert label in md, label


def test_filters():
    assert len(filter_runs(RUNS, source="eval")) == 4 and len(filter_runs(RUNS, source="cli")) == 6
    assert len(filter_runs(RUNS, experiments=["guarded-v6"])) == 2
    assert len(filter_runs(RUNS, since="2026-10-14T06:09")) == 2


def test_empty_log_produces_a_report(tmp_path):
    md, js, m = write_monitoring_report(tmp_path / "none.jsonl", tmp_path / "out" / "monitoring_report.md")
    assert m["total_runs"] == 0 and "No runs in the selected window." in md.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["total_runs"] == 0


def test_generate_monitoring_report_command(tmp_path, monkeypatch):
    from salesops_agent.config import load_config, with_overrides

    cfg = with_overrides(load_config(), logs_dir=tmp_path / "logs", reports_dir=tmp_path / "reports")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in RUNS), encoding="utf-8")
    monkeypatch.setattr(cli, "_load", lambda path: cfg)
    result = CliRunner().invoke(cli.generate_monitoring_report, ["--source", "eval"])
    assert result.exit_code == 0, result.output
    assert "4 runs | success 50.0%" in result.output
    report = (tmp_path / "reports" / "monitoring_report.md").read_text(encoding="utf-8")
    assert "source=eval" in report and (tmp_path / "reports" / "monitoring_report.json").exists()
