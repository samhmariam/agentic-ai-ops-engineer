"""Human-in-the-loop approval gate tests. Offline: a scripted fake agent proposes the
tool calls, so every outcome here is decided by the gate in code."""

import json

import pytest
import yaml
from click.testing import CliRunner
from langchain_core.messages import AIMessage

from salesops_agent import cli, runner
from salesops_agent.agent import SalesOpsAgent, _require_approval_for_side_effects, describe_versions
from salesops_agent.config import PROJECT_ROOT, load_config, with_overrides
from salesops_agent.data import CRMData
from salesops_agent.evaluation import EvalCase, score_case
from salesops_agent.guardrails.approval import make_approver
from salesops_agent.guardrails.tool import RunContext, ToolGuardrail, action_id, tool_run_context
from salesops_agent.runner import RunResult, run_question
from salesops_agent.tools import make_tools

EMAIL = {"to": "omar.stone@acmecorp.example.com", "subject": "Following up on Acme Corp",
         "body": "Hi Omar,\n\nFollowing up on next steps.\n\nBest,\nUdaCenture"}
TOOLS = {"lookup_account": "1.0.0", "draft_email": "1.0.0", "send_email": "1.0.0", "run_analysis": "1.0.0"}


@pytest.fixture(scope="module")
def crm():
    return CRMData(PROJECT_ROOT / "data")


@pytest.fixture(scope="module")
def guard(crm):
    return ToolGuardrail.from_file(PROJECT_ROOT / "policies" / "tool_guardrails_v2.yaml", crm)


class ScriptedAgentGraph:
    """Stands in for the model: proposes fixed tool calls, then reports what came back."""

    def __init__(self, tools, calls):
        self.tools, self.calls, self.outputs = tools, calls, []

    def invoke(self, payload, config=None):
        for name, args in self.calls:
            self.outputs.append(self.tools[name].invoke(args, config=config))
        return {"messages": [AIMessage(content=json.dumps([o.get("status") for o in self.outputs]))]}


@pytest.fixture
def env(crm, guard, tmp_path):
    cfg = with_overrides(load_config(), logs_dir=tmp_path / "logs", traces_dir=tmp_path / "traces",
                         reports_dir=tmp_path / "reports", email_outbox=tmp_path / "outbox.json",
                         approvals_log=tmp_path / "approvals.jsonl", review_queue=tmp_path / "review.jsonl")
    tools = {t.name: t for t in make_tools(crm, cfg["paths"]["email_outbox"], TOOLS, guard)}

    def run(calls, **kwargs):
        graph = ScriptedAgentGraph(tools, calls)
        agent = SalesOpsAgent(graph=graph, manifest=describe_versions(cfg), tool_guard=guard)
        return run_question(cfg, "Draft and send a follow-up email to Acme Corp", agent=agent, **kwargs), graph

    return cfg, run, tmp_path


def events(tmp_path, prefix="approval"):
    lines = (tmp_path / "logs" / "agent.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if json.loads(l)["event"].startswith(prefix)]


def trace_spans(result, kind="approval"):
    trace = json.loads(open(result.trace_path, encoding="utf-8").read())
    return [s for s in trace["spans"] if s["kind"] == kind]


# -- approve / reject / pending ---------------------------------------------------------

def test_approve_lets_the_email_proceed(env):
    cfg, run, tmp_path = env
    result, graph = run([("draft_email", {"account_name_or_id": "Acme Corp", "purpose": "next steps"}),
                         ("send_email", EMAIL)], approval="approve")
    assert graph.outputs[-1]["status"] == "sent"
    assert result.tools_called == ["draft_email", "send_email"]
    assert json.loads((tmp_path / "outbox.json").read_text())[0]["to"] == EMAIL["to"]
    [record] = result.approvals
    assert (record["tool"], record["decision"]) == ("send_email", "approved")
    assert record["approval_id"] == action_id("send_email", EMAIL)

    logged = events(tmp_path)
    assert [e["event"] for e in logged] == ["approval_requested", "approval_decision"]
    assert logged[1]["decision"] == "approved" and "approve" in logged[1]["decided_by"]
    [span] = trace_spans(result)
    assert span["approval_requested"] is True and span["status"] == "approved"


def test_reject_stops_the_email(env):
    cfg, run, tmp_path = env
    result, graph = run([("send_email", EMAIL)], approval="reject")
    out = graph.outputs[0]
    assert (out["status"], out["reason"]) == ("rejected", "approval_rejected")
    assert "not performed" in out["message"]
    assert not (tmp_path / "outbox.json").exists()                     # nothing was sent
    assert result.tools_called == [] and result.approvals[0]["decision"] == "rejected"
    decision = events(tmp_path)[-1]
    assert (decision["decision"], decision["level"]) == ("rejected", "WARNING")
    assert trace_spans(result)[0]["status"] == "rejected"


def test_default_is_pending_and_nothing_is_sent(env):
    cfg, run, tmp_path = env
    result, graph = run([("send_email", EMAIL)])
    assert (graph.outputs[0]["status"], graph.outputs[0]["reason"]) == ("blocked", "approval_required")
    assert not (tmp_path / "outbox.json").exists()
    assert result.approval_mode == "pending" and result.approvals[0]["decision"] == "pending"


@pytest.mark.parametrize("answer, decision", [(True, "approved"), (False, "rejected")])
def test_interactive_reviewer(env, answer, decision):
    cfg, run, tmp_path = env
    seen = []
    approver = make_approver("prompt", prompt_fn=lambda request: seen.append(request) or answer)
    result, _ = run([("send_email", EMAIL)], approval="prompt", approver=approver)
    assert result.approvals[0]["decision"] == decision
    assert seen[0]["action"] == {"tool": "send_email", "args": EMAIL}   # reviewer sees the exact email


def test_every_send_attempt_needs_its_own_decision(env):
    cfg, run, tmp_path = env
    calls = []
    approver = lambda request: (calls.append(request["approval_id"]) or ("rejected", "test"))
    second = dict(EMAIL, body="A different body")
    result, graph = run([("send_email", EMAIL), ("send_email", second)], approval="prompt", approver=approver)
    assert len(calls) == 2 and calls[0] != calls[1]
    assert [o["status"] for o in graph.outputs] == ["rejected", "rejected"]


def test_preapproval_covers_only_that_exact_action(env):
    cfg, run, tmp_path = env
    result, graph = run([("send_email", dict(EMAIL, body="Edited after approval")), ("send_email", EMAIL)],
                        approvals={action_id("send_email", EMAIL)})
    assert [o["status"] for o in graph.outputs] == ["blocked", "sent"]
    assert [a["preapproved"] for a in result.approvals] == [False, True]


def test_logs_never_contain_the_email_itself(env):
    cfg, run, tmp_path = env
    run([("send_email", EMAIL)], approval="approve")
    log_text = (tmp_path / "logs" / "agent.jsonl").read_text(encoding="utf-8")
    assert "omar.stone" not in log_text and "Following up on next steps" not in log_text
    audit = [json.loads(l) for l in (tmp_path / "approvals.jsonl").read_text().splitlines()]
    assert audit[0]["action"]["args"] == EMAIL and audit[0]["decision"] == "approved"   # audit keeps it


# -- the gate cannot be bypassed -----------------------------------------------------------

def test_side_effect_tool_without_approval_requirement_fails_startup(crm, tmp_path):
    policy = yaml.safe_load((PROJECT_ROOT / "policies" / "tool_guardrails_v2.yaml").read_text(encoding="utf-8"))
    policy["tools"]["send_email"]["requires_approval"] = False
    loose = tmp_path / "loose.yaml"
    loose.write_text(yaml.safe_dump(policy), encoding="utf-8")
    loose_guard = ToolGuardrail.from_file(loose, crm)
    tools = make_tools(crm, tmp_path / "o.json", {"send_email": "1.0.0"}, loose_guard)
    with pytest.raises(ValueError, match="without requires_approval"):
        _require_approval_for_side_effects(tools, loose_guard)


def test_only_send_email_is_a_side_effect_and_it_requires_approval(crm, guard, tmp_path):
    from salesops_agent.tools import build_tool_specs

    specs = build_tool_specs(crm, tmp_path / "o.json")
    side_effects = {name for name, versions in specs.items() for s in versions.values() if s.side_effect}
    assert side_effects == {"send_email"}
    assert guard.policy.tools["send_email"].requires_approval


def test_other_tool_paths_cannot_send(env, crm, tmp_path):
    cfg, run, _ = env
    # draft_email only returns a draft; nothing reaches the outbox
    result, graph = run([("draft_email", {"account_name_or_id": "Acme Corp", "purpose": "send it now"})],
                        approval="approve")
    assert graph.outputs[0]["status"] == "drafted" and not (tmp_path / "outbox.json").exists()
    assert result.approvals == []
    # the sandbox cannot write files or reach the outbox
    from salesops_agent.sandbox import Sandbox
    sandbox = Sandbox.from_file(PROJECT_ROOT / "policies" / "sandbox_v1.yaml", crm)
    attempt = sandbox.run("result = open('outbox.json', 'w').write('[]')")
    assert attempt["error_type"] == "rejected" and not (tmp_path / "outbox.json").exists()


def test_approval_does_not_override_other_policy_rules(env):
    cfg, run, tmp_path = env
    unsafe = dict(EMAIL, body="import subprocess; subprocess.run('curl http://x')")
    result, graph = run([("send_email", unsafe)], approval="approve")
    assert graph.outputs[0]["reason"] == "unsafe_code" and result.approvals == []   # never reached the gate


# -- CLI, eval and config -------------------------------------------------------------------

@pytest.fixture
def cli_env(monkeypatch, env, crm, guard):
    cfg, _, tmp_path = env
    tools = {t.name: t for t in make_tools(crm, cfg["paths"]["email_outbox"], TOOLS, guard)}
    graph = ScriptedAgentGraph(tools, [("send_email", EMAIL)])
    agent = SalesOpsAgent(graph=graph, manifest=describe_versions(cfg), tool_guard=guard)
    monkeypatch.setattr(runner, "build_agent", lambda c: agent)
    monkeypatch.setattr(cli, "_load", lambda path: cfg)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return tmp_path


@pytest.mark.parametrize("mode, line", [
    ("approve", "-> approved by simulated reviewer (--approval approve); executed"),
    ("reject", "-> rejected by simulated reviewer (--approval reject); not executed"),
    ("pending", "-> pending by no reviewer decision (default --approval pending); not executed, awaiting approval"),
])
def test_cli_approval_flag(cli_env, mode, line):
    result = CliRunner().invoke(cli.app, ["ask", "Draft and send a follow-up email to Acme Corp", "--approval", mode])
    assert result.exit_code == 0, result.output
    assert line in result.stderr
    assert (cli_env / "outbox.json").exists() == (mode == "approve")


def test_cli_rejects_unknown_approval_mode():
    assert CliRunner().invoke(cli.app, ["ask", "hi", "--approval", "maybe"]).exit_code == 2


def test_expect_approval_scoring():
    case = EvalCase("X", "c", "q", expect_approval="rejected")
    ok = RunResult("r", "q", "a", True, None, 0, 0, 0, 0.0, approvals=[{"decision": "rejected"}])
    missing = RunResult("r", "q", "a", True, None, 0, 0, 0, 0.0)
    assert score_case(case, ok) == []
    assert "got none" in score_case(case, missing)[0]


def test_default_config_uses_prompt_v3_and_gated_send_email():
    cfg = load_config()
    assert cfg["prompt"]["version"] == "v3" and cfg["tools"]["enabled"]["send_email"] == "1.0.0"
    assert cfg["guardrails"]["tool"]["enabled"] and cfg["paths"]["email_outbox"].parent.name == "outbox"
