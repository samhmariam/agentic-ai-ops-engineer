"""Tool/action guardrail tests. Offline: tools are invoked directly or by a scripted
fake agent, so every block shown here is enforced by code, not by model behaviour."""

import json

import pytest
import yaml
from langchain_core.messages import AIMessage
from langchain_core.runnables.config import ContextThreadPoolExecutor

from salesops_agent.agent import SalesOpsAgent, describe_versions
from salesops_agent.config import PROJECT_ROOT, load_config, with_overrides
from salesops_agent.data import CRMData
from salesops_agent.guardrails.tool import (
    RunContext, ToolGuardrail, action_id, load_tool_guardrail, tool_run_context,
)
from salesops_agent.runner import run_question
from salesops_agent.tools import make_tools

POLICY = PROJECT_ROOT / "policies" / "tool_guardrails_v1.yaml"
ALL_TOOLS = {name: "1.0.0" for name in (
    "lookup_account", "lookup_account_context", "list_open_opportunities", "summarize_pipeline",
    "lookup_internal_hr_data", "lookup_internal_financial_data", "draft_email", "send_email",
)}


@pytest.fixture(scope="module")
def crm():
    return CRMData(PROJECT_ROOT / "data")


@pytest.fixture(scope="module")
def guard(crm):
    return ToolGuardrail.from_file(POLICY, crm)


@pytest.fixture
def tools(crm, guard, tmp_path):
    """Every tool, guarded, with a throwaway outbox."""
    outbox = tmp_path / "outbox.json"
    built = {t.name: t for t in make_tools(crm, outbox, ALL_TOOLS, guard)}
    built["_outbox"] = outbox
    return built


def call(tools, name, args, **ctx):
    with tool_run_context(RunContext(**ctx)) as run_ctx:
        return tools[name].invoke(args), run_ctx


# -- the brief's example forbidden actions --------------------------------------

def test_hr_lookup_ceo_bonus_is_blocked(tools):
    result, ctx = call(tools, "lookup_internal_hr_data", {"query": "CEO bonus"})
    assert result["status"] == "blocked"
    assert result["reason"] == "restricted_internal_data"
    assert result["policy"] == "salesops_data_access_policy"
    assert "850000" not in json.dumps(result)                 # tool body never ran
    assert ctx.blocked == [result] and ctx.tool_calls == 0


def test_financial_lookup_m_and_a_is_blocked(tools):
    result, _ = call(tools, "lookup_internal_financial_data", {"query": "CONFIDENTIAL_M_AND_A"})
    assert (result["status"], result["reason"]) == ("blocked", "restricted_internal_data")
    assert "active negotiation" not in json.dumps(result)


def test_send_email_without_approval_is_blocked(tools):
    args = {"to": "omar.stone@acmecorp.example.com", "subject": "Next steps", "body": "Hi Omar"}
    result, _ = call(tools, "send_email", args)
    assert (result["status"], result["reason"]) == ("blocked", "approval_required")
    assert result["approval_id"] == action_id("send_email", args)
    assert not tools["_outbox"].exists()                      # nothing was sent


def test_send_email_runs_only_with_approval_for_that_exact_action(tools):
    args = {"to": "omar.stone@acmecorp.example.com", "subject": "Next steps", "body": "Hi Omar"}
    other = dict(args, body="Different body")
    result, _ = call(tools, "send_email", other, approvals={action_id("send_email", args)})
    assert result["reason"] == "approval_required"           # approval does not transfer
    result, _ = call(tools, "send_email", args, approvals={action_id("send_email", args)})
    assert result["status"] == "sent"
    assert json.loads(tools["_outbox"].read_text())[0]["to"] == args["to"]


# -- authorization and restricted fields ---------------------------------------------

def test_authorized_role_still_cannot_request_restricted_fields(tools):
    result, _ = call(tools, "lookup_internal_hr_data", {"query": "CEO bonus"}, role="hr_admin")
    assert result["reason"] == "restricted_field_request"
    result, _ = call(tools, "lookup_internal_financial_data", {"query": "CONFIDENTIAL_M_AND_A"},
                     role="finance_admin")
    assert result["reason"] == "restricted_field_request"


def test_authorized_role_gets_redacted_results(tools):
    hr, _ = call(tools, "lookup_internal_hr_data", {"query": "list employees and roles"}, role="hr_admin")
    records = hr["data"]["records"]
    assert records and all({"name", "role"} <= set(r) for r in records)
    assert not any(k in r for r in records for k in ("salary_usd", "equity_bonus_usd", "performance_status"))
    fin, _ = call(tools, "lookup_internal_financial_data", {"query": "quarterly revenue"}, role="finance_admin")
    assert "confidential_strategy" not in fin["data"] and "quarterly_summary" in fin["data"]
    assert "active negotiation" not in json.dumps(fin)


def test_wrong_authorized_role_is_blocked(tools):
    result, _ = call(tools, "lookup_internal_hr_data", {"query": "list employees"}, role="finance_admin")
    assert result["reason"] == "restricted_internal_data" and result["role"] == "finance_admin"


# -- task scope and budgets -----------------------------------------------------------

def test_account_lookup_outside_the_request_is_blocked(tools):
    request = "Summarize the account risk for TechStart Inc."
    ok, _ = call(tools, "lookup_account_context", {"account_name_or_id": "TechStart"}, request=request)
    assert ok["account"]["account_id"] == "A003"
    result, _ = call(tools, "lookup_account_context", {"account_name_or_id": "Acme Corp"}, request=request)
    assert (result["reason"], result["account_id"]) == ("out_of_scope_account", "A001")


def test_typo_in_request_still_scopes_correctly(tools):
    ok, _ = call(tools, "lookup_account", {"account_name_or_id": "Acme Corp"}, request="Look up the account Acme Crop.")
    assert ok["account_id"] == "A001"


def test_requests_without_named_accounts_are_budgeted(tools):
    with tool_run_context(RunContext(request="Which accounts look risky?")) as ctx:
        names = ["Acme Corp", "TechStart", "GlobalRetail", "Nimbus Health"]
        results = [tools["lookup_account"].invoke({"account_name_or_id": n}) for n in names]
    assert [r.get("reason") for r in results] == [None, None, None, "lookup_budget_exceeded"]
    assert ctx.account_lookups == 3


def test_total_tool_call_budget(tools):
    with tool_run_context(RunContext()) as ctx:
        results = [tools["summarize_pipeline"].invoke({}) for _ in range(9)]
    assert results[-1]["reason"] == "tool_budget_exceeded" and ctx.tool_calls == 8


def test_unsafe_code_in_arguments_is_blocked(tools):
    for payload in ['__import__("os").system("rm -rf /")', "x; DROP TABLE accounts", "import subprocess"]:
        result, _ = call(tools, "lookup_account", {"account_name_or_id": payload})
        assert result["reason"] == "unsafe_code", payload


def test_tools_missing_from_policy_are_denied(guard):
    blocked = guard.check("run_python", {"code": "print(1)"}, RunContext())
    assert (blocked["reason"], blocked["rule"]) == ("tool_not_allowed", "default_deny")


def test_budgets_are_shared_across_parallel_tool_threads(tools):
    """LangGraph runs tool calls in a context-copying thread pool; counters must be shared."""
    with tool_run_context(RunContext()) as ctx:
        with ContextThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: tools["summarize_pipeline"].invoke({}), range(12)))
    assert ctx.tool_calls == 8
    assert sum(1 for r in results if r.get("reason") == "tool_budget_exceeded") == 4


# -- policy loading ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p["tools"]["lookup_internal_hr_data"].update(authorized_roles=[]), "authorized_roles"),
        (lambda p: p["tools"]["lookup_internal_hr_data"].update(authorized_roles=["ceo"]), "unknown roles"),
        (lambda p: p.update(default_role="intern"), "default_role"),
        (lambda p: p["unsafe_code_patterns"].append("(bad"), "invalid regex"),
        (lambda p: p["messages"].pop("unsafe_code"), "messages missing"),
    ],
    ids=["restricted-without-roles", "unknown-role", "bad-default-role", "bad-regex", "missing-message"],
)
def test_invalid_policy_rejected_at_load(crm, tmp_path, mutate, message):
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    mutate(policy)
    bad = tmp_path / "policy.yaml"
    bad.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(Exception, match=message):
        ToolGuardrail.from_file(bad, crm)


def test_tool_guard_enabled_by_default_disabled_in_baseline(crm):
    assert load_tool_guardrail(load_config(), crm) is not None
    assert load_tool_guardrail(load_config(PROJECT_ROOT / "configs" / "baseline-v1.yaml"), crm) is None
    manifest = describe_versions(load_config())
    assert manifest["guardrails"]["tool"]["policy"] == "salesops_data_access_policy"


# -- runner wiring: blocked calls are explicit, logged and traced ------------------------

class ScriptedAgentGraph:
    """Stands in for the model: proposes a fixed list of tool calls, then answers."""

    def __init__(self, tools, calls):
        self.tools, self.calls, self.outputs = tools, calls, []

    def invoke(self, payload, config=None):
        for name, args in self.calls:   # pass config so callbacks see the call, as LangGraph does
            self.outputs.append(self.tools[name].invoke(args, config=config))
        return {"messages": [AIMessage(content="done")]}


@pytest.fixture
def scripted(crm, guard, tmp_path):
    cfg = with_overrides(load_config(PROJECT_ROOT / "configs" / "tool-guard-only.yaml"),
                         logs_dir=tmp_path / "logs", traces_dir=tmp_path / "traces",
                         reports_dir=tmp_path / "reports", email_outbox=tmp_path / "outbox.json")
    tools = {t.name: t for t in make_tools(crm, cfg["paths"]["email_outbox"], ALL_TOOLS, guard)}

    def build(calls):
        graph = ScriptedAgentGraph(tools, calls)
        return SalesOpsAgent(graph=graph, manifest=describe_versions(cfg), tool_guard=guard), graph

    return cfg, build, tmp_path


def test_runner_reports_logs_and_traces_blocked_calls(scripted):
    cfg, build, tmp_path = scripted
    agent, graph = build([
        ("lookup_account_context", {"account_name_or_id": "Acme Corp"}),
        ("lookup_internal_hr_data", {"query": "CEO bonus"}),
        ("send_email", {"to": "omar.stone@acmecorp.example.com", "subject": "s", "body": "b"}),
    ])
    result = run_question(cfg, "Draft and send a follow-up email to Acme Corp about next steps.", agent=agent)

    assert result.role == "sales_rep"
    assert result.tools_called == ["lookup_account_context"]          # only the allowed call executed
    assert [(b["tool"], b["reason"]) for b in result.tools_blocked] == [
        ("lookup_internal_hr_data", "restricted_internal_data"), ("send_email", "approval_required")]
    assert [o.get("status") for o in graph.outputs] == [None, "blocked", "blocked"]
    assert not (tmp_path / "outbox.json").exists()

    log_text = (tmp_path / "logs" / "agent.jsonl").read_text(encoding="utf-8")
    blocked = [json.loads(l) for l in log_text.splitlines() if '"tool_call_blocked"' in l]
    assert [(e["tool"], e["reason"], e["level"]) for e in blocked] == [
        ("lookup_internal_hr_data", "restricted_internal_data", "WARNING"),
        ("send_email", "approval_required", "WARNING")]
    assert blocked[1]["arg_names"] == ["body", "subject", "to"]
    assert "omar.stone" not in "".join(json.dumps(e) for e in blocked)   # argument values never logged

    trace = json.loads((tmp_path / "traces" / f"{result.run_id}.json").read_text(encoding="utf-8"))
    spans = [s for s in trace["spans"] if s["kind"] == "guardrail"]
    assert [(s["tool"], s["reason"], s["status"]) for s in spans] == [
        ("lookup_internal_hr_data", "restricted_internal_data", "blocked"),
        ("send_email", "approval_required", "blocked")]
    assert trace["tools_blocked"] == result.tools_blocked


def test_runner_role_and_approvals(scripted):
    cfg, build, _ = scripted
    args = {"to": "omar.stone@acmecorp.example.com", "subject": "s", "body": "b"}
    agent, graph = build([("send_email", args)])
    result = run_question(cfg, "Send the approved email to Acme Corp.", agent=agent,
                          approvals={action_id("send_email", args)})
    assert result.tools_called == ["send_email"] and result.tools_blocked == []
    with pytest.raises(ValueError, match="Unknown role"):
        run_question(cfg, "hi", agent=build([])[0], role="ceo")
