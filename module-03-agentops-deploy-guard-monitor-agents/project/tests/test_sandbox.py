"""Sandboxed analysis tests: what run_analysis can do, and every escape route it must refuse.
Offline: code runs in the real sandbox subprocess, no model involved."""

import json

import pytest
import yaml

from salesops_agent.agent import describe_versions
from salesops_agent.config import PROJECT_ROOT, load_config
from salesops_agent.data import CRMData
from salesops_agent.guardrails.tool import RunContext, ToolGuardrail, tool_run_context
from salesops_agent.sandbox import Sandbox, SandboxRejected
from salesops_agent.sandbox.validator import validate
from salesops_agent.tools import make_tools

POLICY = PROJECT_ROOT / "policies" / "sandbox_v1.yaml"


@pytest.fixture(scope="module")
def crm():
    return CRMData(PROJECT_ROOT / "data")


@pytest.fixture(scope="module")
def sandbox(crm):
    return Sandbox.from_file(POLICY, crm)


# -- what it can do: the analyses listed in the brief --------------------------------

ANALYSES = {
    "pipeline value by stage": (
        "from collections import defaultdict\nd = defaultdict(int)\n"
        "for o in data['opportunities']:\n    d[o['stage']] += o['amount_usd']\nresult = dict(d)",
        lambda r: r["Negotiation"] > 0 and sum(r.values()) > 0),
    "count open opportunities": (
        "result = sum(1 for o in data['opportunities'] if o['stage'] not in ('Closed Won', 'Closed Lost'))",
        lambda r: r == 133),
    "average deal size": (
        "import statistics\nresult = round(statistics.mean(o['amount_usd'] for o in data['opportunities'] "
        "if o['stage'] not in ('Closed Won', 'Closed Lost')), 2)",
        lambda r: r == 199436.09),
    "high-risk renewals": (
        "result = sorted(a['name'] for a in data['accounts'] if a['account_status'] == 'customer' "
        "and a['health_score'] is not None and a['health_score'] < 50 and a['contract_end'] <= '2026-09-30')",
        lambda r: r == ["BluePeak Manufacturing", "EduNova Labs", "GlobalRetail Ltd"]),
    "tickets by severity": (
        "from collections import Counter\nresult = dict(Counter(t['severity'] for t in data['support_tickets']))",
        lambda r: r == {"critical": 7, "high": 8, "medium": 10, "low": 8}),
    "health vs renewal date": (
        "from datetime import date\nref = date.fromisoformat(REFERENCE_DATE)\n"
        "rows = [(a['name'], a['health_score'], (date.fromisoformat(a['contract_end']) - ref).days)\n"
        "        for a in data['accounts'] if a['account_status'] == 'customer' and a['contract_end']]\n"
        "result = sorted(rows, key=lambda r: (r[2], r[1]))[:3]",
        lambda r: len(r) == 3 and r[0][2] <= r[1][2]),
}


@pytest.mark.parametrize("name", ANALYSES)
def test_approved_analyses(sandbox, name):
    code, check = ANALYSES[name]
    out = sandbox.run(code)
    assert out["status"] == "ok", out
    assert check(out["result"]), out["result"]


def test_print_is_captured_and_truncated(sandbox):
    out = sandbox.run("print('x' * 5000)\nresult = 1")
    assert out["status"] == "ok" and out["stdout"].startswith("xxx") and "truncated" in out["stdout"]
    assert len(out["stdout"]) < 2100


def test_sets_and_dates_are_serialized(sandbox):
    out = sandbox.run("from datetime import date\nresult = {'s': {3, 1, 2}, 'd': date(2026, 1, 2)}")
    assert out["result"] == {"s": [1, 2, 3], "d": "2026-01-02"}


# -- what it must refuse --------------------------------------------------------------

REJECTED = {
    "eval": "result = eval('1 + 1')",
    "exec": "exec('x = 1')",
    "compile": "result = compile('1', 'f', 'eval')",
    "open file": "result = open('pyproject.toml').read()",
    "__import__": "result = __import__('os').getcwd()",
    "import os": "import os\nresult = os.listdir('.')",
    "import subprocess": "import subprocess",
    "import socket": "import socket",
    "from os import": "from os import path",
    "from urllib": "from urllib import request",
    "relative import": "from . import runner",
    "star import": "from math import *",
    "dunder chain": "result = ().__class__.__bases__[0].__subclasses__()",
    "dunder name": "result = __builtins__",
    "private attribute": "import collections\nresult = collections._sys",
    "str.format escape": "result = '{0.__class__}'.format(1)",
    "generator frame": "g = (x for x in [1])\nresult = g.gi_frame.f_globals",
    "function globals": "f = lambda: 1\nresult = f.func_globals",
    "getattr": "result = getattr(1, 'real')",
    "globals()": "result = globals()",
    "type()": "result = type(1)",
    "class definition": "class A:\n    pass",
    "with statement": "with x:\n    pass",
    "try/except": "try:\n    x = 1\nexcept Exception:\n    pass",
    "global": "def f():\n    global x",
    "decorator": "@min\ndef f():\n    pass",
    "too long": "x = 1\n" * 1000,
    "syntax error": "result = (",
}


@pytest.mark.parametrize("name", REJECTED)
def test_unsafe_code_is_rejected_before_running(sandbox, name):
    out = sandbox.run(REJECTED[name])
    assert (out["status"], out["error_type"]) == ("error", "rejected"), out
    assert out["duration_ms"] < 100        # rejected statically, no process was started


def test_module_proxies_hide_submodules(sandbox):
    # statistics really does expose `sys`; the sandbox's proxy must not.
    out = sandbox.run("import statistics\nresult = statistics.sys.modules")
    assert out["error_type"] == "runtime" and "has no attribute 'sys'" in out["message"]
    out = sandbox.run("import collections\nresult = str(collections.abc)")   # allowed module, sub-module hidden
    assert out["error_type"] == "runtime" and "has no attribute 'abc'" in out["message"]


def test_internal_data_is_not_available(sandbox):
    assert set(sandbox.data) == {"accounts", "opportunities", "activities", "support_tickets",
                                 "product_usage", "contacts"}
    out = sandbox.run("result = sorted(data)")
    assert out["result"] == sorted(sandbox.data)
    for key in ("internal_hr_data", "internal_financial_data"):
        assert sandbox.run(f"result = data['{key}']")["error_type"] == "runtime"


def test_contacts_are_projected_without_pii(sandbox):
    out = sandbox.run("result = sorted({k for c in data['contacts'] for k in c})")
    assert out["result"] == ["account_id", "contact_id", "is_primary", "relationship_status", "title"]


def test_timeout_kills_runaway_code(sandbox):
    out = sandbox.run("while True:\n    pass")
    assert out["error_type"] == "timeout"
    assert out["duration_ms"] < 8000


def test_oversized_result_is_refused(sandbox):
    out = sandbox.run("result = list(range(100000))")
    assert out["error_type"] == "output_too_large"


def test_child_process_has_no_secrets_or_network(sandbox, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    env = sandbox._env()
    assert "OPENAI_API_KEY" not in env and "OPENAI_BASE_URL" not in env and "PATH" not in env
    # even code that slipped past validation could not open a socket: the runner disables it
    from salesops_agent.sandbox import runner
    import socket as real_socket
    original = real_socket.socket
    try:
        runner._disable_network()
        with pytest.raises(PermissionError):
            real_socket.socket()
    finally:
        real_socket.socket = original


def test_validator_reports_all_violations():
    with pytest.raises(SandboxRejected) as exc:
        validate("import os\nresult = eval(x.__class__)", allowed_modules=["math"], forbidden_names=["eval"],
                 forbidden_attribute_prefixes=["_"], forbidden_attributes=[], max_code_chars=1000)
    message = str(exc.value)
    assert "import of 'os'" in message and "'eval'" in message and "__class__" in message


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p["datasets"].update(internal_hr_data=["*"]), "not approved"),
        (lambda p: p["allowed_builtins"].append("eval"), "may never be allowed"),
        (lambda p: p["allowed_modules"].append("os"), "may never be allowed"),
        (lambda p: p["limits"].update(timeout_s=600), "timeout_s"),
    ],
    ids=["hr-dataset", "eval-builtin", "os-module", "huge-timeout"],
)
def test_unsafe_policy_cannot_be_loaded(crm, tmp_path, mutate, message):
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    mutate(policy)
    bad = tmp_path / "sandbox.yaml"
    bad.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(Exception, match=message):
        Sandbox.from_file(bad, crm)


# -- the tool, as the agent sees it -------------------------------------------------------

@pytest.fixture(scope="module")
def tool(crm, sandbox):
    guard = ToolGuardrail.from_file(PROJECT_ROOT / "policies" / "tool_guardrails_v2.yaml", crm)
    return make_tools(crm, PROJECT_ROOT / "reports" / "unused_outbox.json", {"run_analysis": "1.0.0"},
                      guard, sandbox)[0]


def test_tool_runs_analysis_and_describes_datasets(tool):
    assert tool.metadata["version"] == "1.0.0"
    assert "support_tickets(" in tool.description and "REFERENCE_DATE" in tool.description
    with tool_run_context(RunContext()):
        out = tool.invoke({"code": "result = len(data['accounts'])"})
    assert out == {**out, "status": "ok", "result": 109}


def test_tool_guard_screens_code_before_the_sandbox(tool):
    with tool_run_context(RunContext()) as ctx:
        out = tool.invoke({"code": "import os\nresult = os.listdir('.')"})
    assert (out["status"], out["reason"]) == ("blocked", "unsafe_code")       # stopped by the tool guardrail
    assert ctx.blocked and ctx.blocked[0]["tool"] == "run_analysis"


def test_default_config_enables_sandbox():
    manifest = describe_versions(load_config())
    assert manifest["tools"]["run_analysis"] == "1.0.0"
    assert manifest["guardrails"]["sandbox"]["policy_version"] == "v1"
    assert manifest["guardrails"]["tool"]["policy_version"] == "v2"
    older = describe_versions(load_config(PROJECT_ROOT / "configs" / "guarded-v5.yaml"))
    assert "run_analysis" not in older["tools"] and older["guardrails"]["tool"]["policy_version"] == "v1"
