"""Offline tests: config, data access, tools, scoring and reporting. No LLM calls."""

import json

import pytest

from salesops_agent.config import load_config, with_overrides
from salesops_agent.data import CRMData, normalize_lookup_text
from salesops_agent.evaluation import EvalCase, load_cases, score_case
from salesops_agent.prompts import load_system_prompt
from salesops_agent.reporting import build_report
from salesops_agent.runner import RunResult
from salesops_agent.tools import make_tools


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def crm(cfg):
    return CRMData(cfg["paths"]["data_dir"])


def _tools(crm, outbox, enabled):
    return {fn.__name__: fn for fn in make_tools(crm, outbox, enabled)}


def test_config_paths_are_absolute(cfg):
    assert all(p.is_absolute() for p in cfg["paths"].values())
    assert cfg["paths"]["data_dir"].is_dir()


def test_prompt_is_versioned(cfg):
    prompt = load_system_prompt(cfg)
    assert prompt.version == "v1"
    assert "SalesOps Agent for UdaCenture" in prompt.text


def test_dataset_counts_match_notebook(crm):
    assert len(crm.accounts) == 109
    assert sum(a["account_status"] == "customer" for a in crm.accounts) == 27
    assert len(crm.contacts) == 280
    assert len(crm.opportunities) == 182


def test_account_names_unique_after_normalization(crm):
    names = [normalize_lookup_text(a["name"]) for a in crm.accounts]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("query", ["TechStart Inc", "TechStart Inc.", "techstart", "A003", "Techstrat"])
def test_resolve_account_variants(crm, query):
    assert crm.resolve_account(query)["account_id"] == "A003"


def test_resolve_account_typo_uses_fuzzy_match(crm):
    # The notebook's fuzzy fallback raised NameError (difflib never imported).
    assert crm.resolve_account("Acme Crop")["name"] == "Acme Corp"


def test_resolve_unknown_account(crm):
    assert crm.resolve_account("Nonexistent Widgets") is None


def test_tools_respect_enabled_list(cfg, crm, tmp_path):
    tools = _tools(crm, tmp_path / "outbox.json", ["lookup_account", "summarize_pipeline"])
    assert set(tools) == {"lookup_account", "summarize_pipeline"}
    with pytest.raises(ValueError):
        make_tools(crm, tmp_path / "outbox.json", ["drop_tables"])


def test_pipeline_summary_counts(cfg, crm, tmp_path):
    summary = _tools(crm, tmp_path / "o.json", ["summarize_pipeline"])["summarize_pipeline"]()
    assert sum(s["count"] for s in summary.values()) == 182


def test_draft_and_send_email_use_configured_outbox(cfg, crm, tmp_path):
    outbox = tmp_path / "outbox.json"
    tools = _tools(crm, outbox, ["draft_email", "send_email"])
    draft = tools["draft_email"]("Acme Corp", "next steps")
    assert draft["to"] == "omar.stone@acmecorp.example.com"
    tools["send_email"](draft["to"], draft["subject"], draft["body"])
    assert json.loads(outbox.read_text())[0]["status"] == "sent"


def test_eval_cases_load(cfg):
    cases = load_cases(cfg["paths"]["eval_cases"])
    assert len({c.id for c in cases}) == len(cases) >= 8


def _run(answer="", tools=(), error=None):
    return RunResult("r1", "q", answer, error is None, error, 0.1, 10, 5, 0.0, list(tools))


def test_score_case_checks():
    case = EvalCase("X", "c", "q", expected_tools=["a"], forbidden_tools=["b"],
                    must_contain=["Hello"], must_not_contain=["secret"])
    assert score_case(case, _run("hello world", ["a"])) == []
    failures = score_case(case, _run("SECRET", ["b"]))
    assert len(failures) == 4
    assert score_case(case, _run(error="Boom"))[0].startswith("run failed")


def test_report_builds_without_runs(cfg, tmp_path):
    out = build_report(with_overrides(cfg, logs_dir=tmp_path / "logs", reports_dir=tmp_path / "reports"))
    text = out.read_text(encoding="utf-8")
    assert "No runs logged yet" in text and "No evaluation results" in text
