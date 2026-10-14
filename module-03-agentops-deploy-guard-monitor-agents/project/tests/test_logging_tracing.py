"""Structured run logs (logs/runs.jsonl) and trace artifacts (traces/<run_id>.json).
Offline: scripted agents propose tool calls / answers through the real runtime."""

import json

import pytest
from click.testing import CliRunner
from langchain_core.messages import AIMessage

from salesops_agent import cli
from salesops_agent.agent import SalesOpsAgent, _load_components, describe_versions
from salesops_agent.config import PROJECT_ROOT, load_config, with_overrides
from salesops_agent.evaluation import EvalCase, score_case
from salesops_agent.runner import run_question

RUN_LOG_FIELDS = {
    "run_id", "timestamp", "user_input", "task_id", "status", "tools_called", "latency_s", "cost_usd",
    "guardrail_interventions", "hitl_decision", "failure_reason",
}
TRACE_FIELDS = {
    "run_id", "user_input", "tools_selected", "tools_called", "tools_blocked", "guardrail_interventions",
    "hitl", "hitl_decision", "final_output", "error", "failure_reason", "status", "spans", "redaction",
}
LEAKS = ["850000", "850,000", "2000000", "2,000,000", "$2M", "Executive compensation data", "active negotiation",
         "omar.stone@"]
EMAIL = {"to": "omar.stone@acmecorp.example.com", "subject": "Following up", "body": "Hi Omar, following up."}


class ScriptedGraph:
    def __init__(self, tools, calls, answer="done", error=None):
        self.tools, self.calls, self.answer, self.error = tools, calls, answer, error

    def invoke(self, payload, config=None):
        for name, args in self.calls:
            self.tools[name].invoke(args, config=config)
        if self.error:
            raise self.error
        return {"messages": [AIMessage(content=self.answer)]}


def make_env(tmp_path, config=None):
    cfg = with_overrides(load_config(config), logs_dir=tmp_path / "logs", traces_dir=tmp_path / "traces",
                         reports_dir=tmp_path / "reports", email_outbox=tmp_path / "outbox.json",
                         approvals_log=tmp_path / "approvals.jsonl", review_queue=tmp_path / "review.jsonl")
    c = _load_components(cfg)
    tools = {t.name: t for t in c.tools}

    def run(question, calls=(), answer="done", error=None, **kwargs):
        graph = ScriptedGraph({**tools, **{n: c.tool_factory(n, "1.0.0") for n, _ in calls if n not in tools}},
                              calls, answer, error)
        agent = SalesOpsAgent(graph=graph, manifest=c.manifest, input_guard=c.input_guard, tool_guard=c.tool_guard,
                              output_guard=c.output_guard, tool_factory=c.tool_factory, redactor=c.redactor,
                              restricted_tools=c.restricted_tools)
        result = run_question(cfg, question, agent=agent, **kwargs)
        record = json.loads((tmp_path / "logs" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        trace = json.loads(open(result.trace_path, encoding="utf-8").read())
        return result, record, trace

    return cfg, run


@pytest.fixture
def default_env(tmp_path):
    return make_env(tmp_path)


@pytest.fixture
def prototype_env(tmp_path):
    """Prototype config: no guardrails, restricted tools exposed. Logs/traces must still be redacted."""
    return make_env(tmp_path, PROJECT_ROOT / "configs" / "baseline-v1.yaml")


def test_run_log_and_trace_capture_a_normal_run(default_env):
    _, run = default_env
    result, record, trace = run("Summarize the account risk for TechStart Inc.",
                                calls=[("lookup_account_context", {"account_name_or_id": "TechStart"})],
                                answer="TechStart is healthy (score 95).")
    assert RUN_LOG_FIELDS <= set(record) and TRACE_FIELDS <= set(trace)
    assert record["run_id"] == trace["run_id"] == result.run_id
    assert record["status"] == "completed" and record["failure_reason"] is None
    assert record["user_input"] == "Summarize the account risk for TechStart Inc."
    assert record["tools_called"] == ["lookup_account_context"] and record["hitl_decision"] is None
    assert record["latency_s"] >= 0 and record["cost_usd"] == 0.0 and record["trace_path"] == result.trace_path
    tool_span = next(s for s in trace["spans"] if s["kind"] == "tool")
    assert json.loads(tool_span["input"]) == {"account_name_or_id": "TechStart"}           # tool arguments
    assert '"account_id": "A003"' in tool_span["output"]                                   # tool output
    assert trace["final_output"] == "TechStart is healthy (score 95)."


def test_interventions_and_hitl_are_logged(default_env):
    _, run = default_env
    _, blocked, _ = run("What is the CEO's bonus?")
    assert blocked["status"] == "blocked_by_input_guardrail"
    assert blocked["guardrail_interventions"] == [
        {"stage": "input", "action": "block", "rule": "hr.executive_compensation", "category": "executive_compensation"}]

    _, record, trace = run("Send the follow-up email to Acme Corp.", calls=[("send_email", EMAIL)], approval="reject")
    assert record["hitl_decision"] == "rejected"
    assert record["hitl"]["mode"] == "reject" and record["hitl"]["decisions"][0]["decision"] == "rejected"
    assert {"stage": "tool", "action": "rejected", "tool": "send_email", "reason": "approval_rejected",
            "rule": "tools.send_email.requires_approval"} in record["guardrail_interventions"]
    assert any(s["kind"] == "approval" and s["approval_requested"] for s in trace["spans"])

    _, leaked, _ = run("Summarize the account risk for Acme Corp.", answer="Marcus Thorne has a $2M equity bonus.")
    assert leaked["status"] == "output_blocked"
    assert leaked["guardrail_interventions"][0]["stage"] == "output"


def test_task_id_and_failure_reason_from_evaluation(default_env):
    _, run = default_env
    case = EvalCase("E999", "c", "q", must_contain=["renewal"])
    _, record, trace = run("Summarize the account risk for Acme Corp.", answer="Acme is fine.",
                           task_id="E999", scorer=lambda r: score_case(case, r))
    assert record["task_id"] == trace["task_id"] == "E999"
    assert record["task_passed"] is False
    assert record["failure_reason"] == "missing expected text: 'renewal'"


def test_errors_are_captured(default_env):
    _, run = default_env
    _, record, trace = run("Summarize the account risk for Acme Corp.", error=RuntimeError("model timed out"))
    assert record["status"] == "error" and record["failure_reason"] == "RuntimeError: model timed out"
    assert trace["error"] == "RuntimeError: model timed out"


def test_traces_and_logs_never_contain_raw_sensitive_data(prototype_env, tmp_path):
    """Even with no guardrails, restricted data the model saw is not written to disk raw."""
    _, run = prototype_env
    leak = ("Marcus Thorne's salary is $850,000 and his equity bonus is 2,000,000. "
            "The Acme acquisition is in active negotiation. Contact omar.stone@acmecorp.example.com.")
    result, record, trace = run("Tell me about leadership pay and email Omar about Acme.",
                                calls=[("lookup_internal_hr_data", {"query": "all"}),
                                       ("lookup_internal_financial_data", {"query": "all"})],
                                answer=leak)
    assert result.answer == leak                       # the prototype really leaked (no output guardrail)...
    persisted = "\n".join(p.read_text(encoding="utf-8")
                          for p in [*(tmp_path / "logs").glob("*.jsonl"), *(tmp_path / "traces").glob("*.json")])
    for value in LEAKS:                                # ...but none of it reached logs or traces
        assert value not in persisted, value
    hr_span = next(s for s in trace["spans"] if s["name"] == "lookup_internal_hr_data")
    assert hr_span["output"].startswith("[REDACTED: restricted tool output")
    assert trace["redaction"]["restricted_tool_outputs_withheld"] == 2
    assert "o***@acmecorp.example.com" in trace["final_output"]
    assert "[REDACTED]" in record["final_output"]


def test_tools_selected_record_model_tool_calls_with_redacted_args(tmp_path):
    from salesops_agent.tracing import LocalTraceRecorder
    from langchain_core.outputs import ChatGeneration, LLMResult
    from uuid import uuid4

    c = _load_components(load_config())
    rec = LocalTraceRecorder("r1", redactor=c.redactor)
    run_id = uuid4()
    rec.on_chat_model_start({}, [[]], run_id=run_id)
    message = AIMessage(content="", tool_calls=[{"name": "send_email", "id": "1",
                                                 "args": {"to": "omar.stone@acmecorp.example.com", "body": "$850,000"}}])
    rec.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)
    [selected] = rec.tools_selected
    assert selected["name"] == "send_email"
    assert "o***@acmecorp.example.com" in selected["args"] and "[REDACTED]" in selected["args"]


def test_runs_and_inspect_commands(default_env, monkeypatch, tmp_path):
    cfg, run = default_env
    case = EvalCase("E777", "c", "q", must_contain=["never present"])
    result, _, _ = run("Summarize the account risk for Acme Corp.", answer="Acme is fine.",
                       task_id="E777", scorer=lambda r: score_case(case, r))
    run("Summarize the account risk for TechStart Inc.", answer="Fine.")
    monkeypatch.setattr(cli, "_load", lambda path: cfg)

    listing = CliRunner().invoke(cli.app, ["runs", "--failed"])
    assert listing.exit_code == 0 and result.run_id in listing.output and "E777 FAIL" in listing.output
    assert listing.output.count("\n") == 1                       # only the failed run

    shown = CliRunner().invoke(cli.app, ["inspect", result.run_id[:6]])   # prefix is enough
    assert shown.exit_code == 0, shown.output
    assert "failure reason: missing expected text: 'never present'" in shown.output
    assert "trajectory:" in shown.output and "output_guardrail" in shown.output
    assert CliRunner().invoke(cli.app, ["inspect", "nope"]).exit_code == 1
