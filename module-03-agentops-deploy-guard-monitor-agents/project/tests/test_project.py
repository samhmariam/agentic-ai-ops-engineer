"""Offline tests: config, data access, tools, scoring and reporting. No LLM calls."""

import copy
import json

import pytest
import yaml
from pydantic import ValidationError

from salesops_agent.agent import describe_versions
from salesops_agent.config import ConfigError, load_config, with_overrides
from salesops_agent.data import CRMData, normalize_lookup_text
from salesops_agent.evaluation import EvalCase, load_cases, score_case
from salesops_agent.prompts import load_system_prompt, prompt_hash
from salesops_agent.reporting import build_report
from salesops_agent.runner import RunResult
from salesops_agent.schemas import DataValidationError
from salesops_agent.tools import make_tools, tool_versions
from salesops_agent.versions import short_manifest


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def crm(cfg):
    return CRMData(cfg["paths"]["data_dir"])


def _tools(crm, outbox, enabled):
    """enabled: {name: version}, or a list of names to build at 1.0.0."""
    if isinstance(enabled, list):
        enabled = {name: "1.0.0" for name in enabled}
    return {t.name: t for t in make_tools(crm, outbox, enabled)}


def test_config_paths_are_absolute(cfg):
    assert all(p.is_absolute() for p in cfg["paths"].values())
    assert cfg["paths"]["data_dir"].is_dir()
    assert cfg["schema_version"] == 1
    assert len(cfg["config_sha256"]) == 64


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.pop("schema_version"),
        lambda c: c.update(schema_version=2),
        lambda c: c["model"].update(temperature=5),
        lambda c: c["tools"].update(enabled={"lookup_account": "1.0"}),
        lambda c: c["tools"].update(enabled=["lookup_account"]),
        lambda c: c["paths"].update(unexpected="x"),
        lambda c: c.pop("experiment"),
        lambda c: c["experiment"].update(name="Has Spaces"),
    ],
    ids=["missing-version", "future-version", "bad-temperature", "non-semver-tool",
         "unpinned-tool-list", "unknown-key", "missing-experiment", "bad-experiment-name"],
)
def test_invalid_config_rejected(cfg, tmp_path, mutate):
    mutate(raw := _raw_config_with_absolute_paths(cfg))
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, raw))


def test_copied_config_loads(cfg, tmp_path):
    # Control for the rejection cases: an unmutated copy must load.
    assert load_config(_write_config(tmp_path, _raw_config_with_absolute_paths(cfg)))


def _raw_config_with_absolute_paths(cfg):
    raw = yaml.safe_load(open(cfg["config_path"], encoding="utf-8"))
    raw["paths"] = {k: str(v) for k, v in cfg["paths"].items()}
    raw["prompt"]["registry"] = str(cfg["prompt"]["registry"])
    return raw


def _write_config(tmp_path, raw):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_prompt_is_versioned(cfg):
    prompt = load_system_prompt(cfg)
    assert prompt.version == "v1"
    assert "SalesOps Agent for UdaCenture" in prompt.text
    assert len(prompt.sha256) == 64


def test_prompt_hash_ignores_line_endings():
    assert prompt_hash("a\nb\n") == prompt_hash("a\r\nb\r\n")


def _copy_prompts(cfg, tmp_path):
    for f in cfg["prompt"]["registry"].parent.iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    return with_prompt(cfg, tmp_path / "registry.yaml")


def with_prompt(cfg, registry, version=None):
    new = copy.deepcopy(cfg)
    new["prompt"]["registry"] = registry
    if version:
        new["prompt"]["version"] = version
    return new


def test_edited_prompt_fails_hash_check(cfg, tmp_path):
    tmp_cfg = _copy_prompts(cfg, tmp_path)
    (tmp_path / "system_prompt_v1.md").write_text("You are a different agent.", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        load_system_prompt(tmp_cfg)


def test_unknown_prompt_version_fails(cfg, tmp_path):
    with pytest.raises(ValueError, match="not in"):
        load_system_prompt(with_prompt(cfg, cfg["prompt"]["registry"], version="v99"))


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
    with pytest.raises(ValueError, match="unknown tool 'drop_tables'"):
        make_tools(crm, tmp_path / "outbox.json", {"drop_tables": "1.0.0"})
    with pytest.raises(ValueError, match=r"no version 9.9.9 \(available: \['1.0.0', '1.1.0'\]\)"):
        make_tools(crm, tmp_path / "outbox.json", {"list_open_opportunities": "9.9.9"})


def test_tool_versions_coexist_and_differ(crm, tmp_path):
    v1_0 = _tools(crm, tmp_path / "o.json", {"list_open_opportunities": "1.0.0"})["list_open_opportunities"]
    v1_1 = _tools(crm, tmp_path / "o.json", {"list_open_opportunities": "1.1.0"})["list_open_opportunities"]
    assert v1_0.metadata["version"] == "1.0.0" and v1_1.metadata["version"] == "1.1.0"
    all_open = v1_0.invoke({})
    capped = v1_1.invoke({"limit": 5})
    assert len(all_open) == capped["total_matching"] == 133
    assert capped["returned"] == len(capped["opportunities"]) == 5
    amounts = [o["amount_usd"] for o in capped["opportunities"]]
    assert amounts == sorted(amounts, reverse=True)
    assert capped["total_amount_usd"] == sum(o["amount_usd"] for o in all_open)
    assert "limit" in v1_1.args and "limit" not in v1_0.args


def test_pipeline_summary_counts(cfg, crm, tmp_path):
    summary = _tools(crm, tmp_path / "o.json", ["summarize_pipeline"])["summarize_pipeline"].invoke({})
    assert sum(s["count"] for s in summary.values()) == 182


def test_draft_and_send_email_use_configured_outbox(cfg, crm, tmp_path):
    outbox = tmp_path / "outbox.json"
    tools = _tools(crm, outbox, ["draft_email", "send_email"])
    draft = tools["draft_email"].invoke({"account_name_or_id": "Acme Corp", "purpose": "next steps"})
    assert draft["to"] == "omar.stone@acmecorp.example.com"
    tools["send_email"].invoke({k: draft[k] for k in ("to", "subject", "body")})
    assert json.loads(outbox.read_text())[0]["status"] == "sent"


def test_every_tool_is_versioned_with_risk_metadata(cfg, crm, tmp_path):
    tools = make_tools(crm, tmp_path / "o.json", cfg["tools"]["enabled"])
    versions = tool_versions(tools)
    assert set(versions) == set(cfg["tools"]["enabled"])
    assert all(v == "1.0.0" for v in versions.values())
    by_name = {t.name: t.metadata for t in tools}
    assert by_name["send_email"]["side_effect"] is True
    assert by_name["lookup_internal_hr_data"]["classification"] == "restricted"
    assert by_name["lookup_account"]["classification"] == "crm"


@pytest.mark.parametrize(
    "name, args",
    [
        ("lookup_account", {"account_name_or_id": ""}),
        ("lookup_account", {}),
        ("send_email", {"to": "not-an-email", "subject": "s", "body": "b"}),
        ("send_email", {"to": "a@b.com", "subject": "", "body": "b"}),
    ],
)
def test_tool_inputs_are_validated(crm, tmp_path, name, args):
    outbox = tmp_path / "o.json"
    tool = _tools(crm, outbox, [name])[name]
    with pytest.raises(ValidationError):
        tool.invoke(args)
    assert not outbox.exists()


def test_tool_schema_exposed_to_model(crm, tmp_path):
    tool = _tools(crm, tmp_path / "o.json", ["list_open_opportunities"])["list_open_opportunities"]
    assert "Negotiation" in tool.args["stage"]["description"]


def test_invalid_data_fails_on_load(cfg, tmp_path):
    for f in cfg["paths"]["data_dir"].glob("*.json"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    accounts = json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8"))
    accounts[0]["health_score"] = 250
    (tmp_path / "accounts.json").write_text(json.dumps(accounts), encoding="utf-8")
    with pytest.raises(DataValidationError, match=r"accounts.json\[0\]"):
        CRMData(tmp_path)


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


def test_version_manifest_pins_everything(cfg):
    manifest = describe_versions(cfg)
    assert manifest["agent_version"] == cfg["agent"]["version"]
    assert manifest["prompt_version"] == "v1"
    assert manifest["prompt_sha256"] == load_system_prompt(cfg).sha256
    assert manifest["config_sha256"] == cfg["config_sha256"]
    assert manifest["config_schema_version"] == 1
    assert manifest["data_schema_version"] == "1.0"
    assert set(manifest["tools"]) == set(cfg["tools"]["enabled"])
    assert set(manifest["git"]) == {"commit", "dirty"}
    assert any(line.startswith("prompt v1 (") for line in short_manifest(manifest))


def test_report_includes_eval_versions(cfg, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    manifest = describe_versions(cfg)
    ev = {"timestamp": "20260101T000000Z", "versions": manifest, "total": 1, "passed": 1,
          "pass_rate": 1.0, "results": [{"case_id": "E1", "category": "c", "passed": True, "failures": []}]}
    (reports / "eval_20260101T000000Z.json").write_text(json.dumps(ev), encoding="utf-8")
    text = build_report(with_overrides(cfg, logs_dir=tmp_path / "logs", reports_dir=reports)).read_text(encoding="utf-8")
    assert "## Versions under evaluation" in text
    assert f"prompt v1 ({manifest['prompt_sha256'][:12]})" in text


def test_extends_merges_overrides_and_removes(cfg, tmp_path):
    base = _write_config(tmp_path, _raw_config_with_absolute_paths(cfg))
    child_dir = tmp_path / "configs"
    child_dir.mkdir()
    child = child_dir / "exp.yaml"
    child.write_text(
        "extends: ../config.yaml\n"
        "experiment: {name: exp-a}\n"
        "model: {temperature: 0.5}\n"
        "tools:\n  enabled:\n    lookup_internal_hr_data: null\n    list_open_opportunities: '1.1.0'\n"
        "paths: {reports_dir: out}\n",
        encoding="utf-8",
    )
    merged = load_config(child)
    assert merged["experiment"]["name"] == "exp-a"
    assert merged["model"] == {"name": cfg["model"]["name"], "temperature": 0.5}
    assert "lookup_internal_hr_data" not in merged["tools"]["enabled"]
    assert merged["tools"]["enabled"]["list_open_opportunities"] == "1.1.0"
    assert merged["tools"]["enabled"]["send_email"] == "1.0.0"
    # child-relative path resolves against the child file; inherited ones are untouched
    assert merged["paths"]["reports_dir"] == child_dir / "out"
    assert merged["paths"]["data_dir"] == cfg["paths"]["data_dir"]
    assert merged["config_files"] == [str(child.resolve()), str(base.resolve())]
    assert merged["config_sha256"] != load_config(base)["config_sha256"]


def test_extends_cycle_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text("extends: b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("extends: a.yaml\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Circular"):
        load_config(tmp_path / "a.yaml")


def test_config_hash_is_content_based(cfg, tmp_path):
    # Same effective config, different file text (comments, key order) -> same hash.
    raw = _raw_config_with_absolute_paths(cfg)
    first = load_config(_write_config(tmp_path, raw))["config_sha256"]
    reordered = "# a comment\n" + yaml.safe_dump(dict(reversed(list(raw.items()))), sort_keys=False)
    (tmp_path / "config.yaml").write_text(reordered, encoding="utf-8")
    assert load_config(tmp_path / "config.yaml")["config_sha256"] == first
