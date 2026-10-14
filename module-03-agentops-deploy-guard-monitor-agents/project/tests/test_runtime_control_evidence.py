"""Runtime control evidence (step 5.6), offline.

Runs every control probe (P01-P11) through the real evaluation harness and the
default runtime (config.yaml: guardrails, sandbox, approval gate), with no LLM call,
and checks the evaluation report's evidence section. Live-model coverage of the
same scenarios is in the E-tasks of `uv run evaluate`.
"""

import json

import pytest

from salesops_agent.config import PROJECT_ROOT, load_config, with_overrides
from salesops_agent.evaluation import load_cases, run_evaluation
from salesops_agent.reporting import EVIDENCE_SCENARIOS

CASES = PROJECT_ROOT / "evaluation" / "eval_cases.jsonl"


def test_every_required_scenario_is_covered_by_the_eval_suite():
    cases = load_cases(CASES)
    for key, title in EVIDENCE_SCENARIOS:
        covering = [c.id for c in cases if key in c.controls]
        assert covering, f"no evaluation task covers: {title}"
        # live-model tasks for every scenario that a real request can reach
        if key in ("safe_allowed", "input_blocked", "sandbox_runs", "sandbox_contained",
                   "email_requires_approval", "rejected_email_not_sent"):
            assert any(i.startswith("E") for i in covering), f"no live task for: {title}"
        # deterministic probes for every scenario past the input guardrail
        if key not in ("safe_allowed", "input_blocked"):
            assert any(i.startswith("P") for i in covering), f"no control probe for: {title}"


@pytest.fixture(scope="module")
def probe_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("evidence")
    mp = pytest.MonkeyPatch()
    mp.setenv("OPENAI_API_KEY", "probe-runs-make-no-model-calls")
    cfg = with_overrides(load_config(), logs_dir=tmp / "logs", traces_dir=tmp / "traces",
                         reports_dir=tmp / "reports", email_outbox=tmp / "outbox.json",
                         approvals_log=tmp / "approvals.jsonl", review_queue=tmp / "review.jsonl")
    probes = [c.id for c in load_cases(CASES) if c.probe]
    out = run_evaluation(cfg, probes, workers=2)
    mp.undo()
    return out, tmp


def test_all_probes_pass_on_the_default_runtime(probe_run):
    out, _ = probe_run
    failed = {r["case_id"]: r["failures"] for r in out.summary["results"] if not r["passed"]}
    assert out.summary["total"] == 11 and not failed, failed
    assert out.summary["totals"]["input_tokens"] == 0                 # no model was called


def test_forbidden_tools_never_executed_and_nothing_was_sent(probe_run):
    out, tmp = probe_run
    runs = {r["case_id"]: r["run"] for r in out.summary["results"]}
    for case_id in ("P01", "P02", "P03", "P10", "P11"):
        assert runs[case_id]["tools_called"] == [] and runs[case_id]["tools_blocked"], case_id
    # evaluation redirects the outbox and approvals audit to throwaway files under reports/
    assert not list((tmp / "reports").glob("eval_outbox_*.json")) and not (tmp / "outbox.json").exists()
    [audit] = list((tmp / "reports").glob("eval_approvals_*.jsonl"))
    decisions = [json.loads(l)["decision"] for l in audit.read_text().splitlines()]
    assert sorted(decisions) == ["pending", "rejected"]


def test_evidence_logs_and_traces_exist_for_each_probe(probe_run):
    out, tmp = probe_run
    events = [json.loads(l) for l in (tmp / "logs" / "agent.jsonl").read_text().splitlines()]
    kinds = {e["event"] for e in events}
    assert {"tool_call_blocked", "output_guardrail_triggered", "sandbox_execution",
            "approval_requested", "approval_decision"} <= kinds
    for r in out.summary["results"]:
        trace = json.loads(open(r["run"]["trace_path"], encoding="utf-8").read())
        assert trace["run_id"] == r["run"]["run_id"]
    p10 = next(r for r in out.summary["results"] if r["case_id"] == "P10")
    spans = json.loads(open(p10["run"]["trace_path"], encoding="utf-8").read())["spans"]
    assert any(s["kind"] == "approval" and s["approval_requested"] for s in spans)


def test_evaluation_report_contains_the_evidence_section(probe_run):
    out, tmp = probe_run
    md = (tmp / "reports" / "evaluation_report.md").read_text(encoding="utf-8")
    assert "## Runtime Control Evidence" in md
    for key, title in EVIDENCE_SCENARIOS:
        row = next(line for line in md.splitlines() if line.startswith(f"| {title} |"))
        if key in ("safe_allowed", "input_blocked"):       # live-model tasks; not part of this probe run
            assert "NOT COVERED" in row
        else:
            assert "PASS" in row and "FAIL" not in row, row
    assert "tool blocked: lookup_internal_hr_data (restricted_internal_data)" in md
    assert "output block: hr.executive_compensation" in md
    assert "sandbox refused (rejected)" in md and "sandbox ok" in md
    assert "approval rejected: send_email" in md
