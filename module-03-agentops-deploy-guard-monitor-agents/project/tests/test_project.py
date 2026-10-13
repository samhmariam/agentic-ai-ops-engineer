"""Offline tests: config, data access, tools, scoring and reporting. No LLM calls."""

import copy
import json

import pytest
import yaml
from pydantic import ValidationError

from salesops_agent.agent import describe_versions
from salesops_agent.config import PROJECT_ROOT, ConfigError, load_config, with_overrides
from salesops_agent.data import CRMData, normalize_lookup_text
from salesops_agent.comparison import compare, render_markdown, resolve_eval
from salesops_agent.evaluation import EvalCase, dataset_fingerprint, load_cases, score_case
from salesops_agent.prompts import load_system_prompt, prompt_hash
from salesops_agent.reporting import build_report, latest_eval, p95
from salesops_agent.runner import RunResult
from salesops_agent.schemas import DataValidationError
from salesops_agent.tools import make_tools, tool_versions
from salesops_agent.versions import short_manifest


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def baseline_cfg():
    """The prototype snapshot: prompt v1, every tool including restricted ones, no guardrails."""
    return load_config(PROJECT_ROOT / "configs" / "baseline-v1.yaml")


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
    raw["guardrails"]["input"]["policy"] = str(cfg["guardrails"]["input"]["policy"])
    return raw


def _write_config(tmp_path, raw):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_prompt_is_versioned(cfg):
    prompt = load_system_prompt(cfg)
    assert prompt.version == cfg["prompt"]["version"]
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
    (tmp_path / load_system_prompt(cfg).path.name).write_text("You are a different agent.", encoding="utf-8")
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


def test_every_tool_is_versioned_with_risk_metadata(baseline_cfg, crm, tmp_path):
    tools = make_tools(crm, tmp_path / "o.json", baseline_cfg["tools"]["enabled"])
    versions = tool_versions(tools)
    assert set(versions) == set(baseline_cfg["tools"]["enabled"])
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
    assert manifest["prompt_version"] == cfg["prompt"]["version"]
    assert manifest["prompt_sha256"] == load_system_prompt(cfg).sha256
    assert manifest["config_sha256"] == cfg["config_sha256"]
    assert manifest["config_schema_version"] == 1
    assert manifest["data_schema_version"] == "1.0"
    assert set(manifest["tools"]) == set(cfg["tools"]["enabled"])
    assert set(manifest["git"]) == {"commit", "dirty"}
    assert any(line.startswith(f"prompt {cfg['prompt']['version']} (") for line in short_manifest(manifest))


def test_report_includes_eval_versions(cfg, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    manifest = describe_versions(cfg)
    ev = {"timestamp": "20260101T000000Z", "versions": manifest, "total": 1, "passed": 1,
          "pass_rate": 1.0, "results": [{"case_id": "E1", "category": "c", "passed": True, "failures": []}]}
    (reports / "eval_20260101T000000Z.json").write_text(json.dumps(ev), encoding="utf-8")
    text = build_report(with_overrides(cfg, logs_dir=tmp_path / "logs", reports_dir=reports)).read_text(encoding="utf-8")
    assert "## Versions under evaluation" in text
    assert f"prompt {manifest['prompt_version']} ({manifest['prompt_sha256'][:12]})" in text


def test_extends_merges_overrides_and_removes(cfg, tmp_path):
    base = _write_config(tmp_path, _raw_config_with_absolute_paths(cfg))
    child_dir = tmp_path / "configs"
    child_dir.mkdir()
    child = child_dir / "exp.yaml"
    child.write_text(
        "extends: ../config.yaml\n"
        "experiment: {name: exp-a}\n"
        "model: {temperature: 0.5}\n"
        "tools:\n  enabled:\n    draft_email: null\n    send_email: '1.0.0'\n    list_open_opportunities: '1.0.0'\n"
        "paths: {reports_dir: out}\n",
        encoding="utf-8",
    )
    merged = load_config(child)
    assert merged["experiment"]["name"] == "exp-a"
    assert merged["model"]["temperature"] == 0.5                       # overridden
    assert merged["model"]["name"] == cfg["model"]["name"]             # inherited
    assert merged["model"]["timeout_s"] == cfg["model"]["timeout_s"]   # inherited
    assert "draft_email" not in merged["tools"]["enabled"]                     # removed
    assert merged["tools"]["enabled"]["list_open_opportunities"] == "1.0.0"   # overridden
    assert merged["tools"]["enabled"]["send_email"] == "1.0.0"                # added
    assert merged["tools"]["enabled"]["lookup_account"] == "1.0.0"            # inherited
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


@pytest.mark.parametrize("path", sorted((PROJECT_ROOT / "configs").glob("*.yaml")), ids=lambda p: p.stem)
def test_experiment_configs_load_and_build(path, tmp_path):
    exp = load_config(path)
    assert exp["experiment"]["name"] == path.stem
    manifest = describe_versions(exp)
    assert manifest["experiment"] == path.stem
    assert manifest["prompt_sha256"] == load_system_prompt(exp).sha256


def test_every_registered_prompt_matches_its_hash(cfg):
    registry = yaml.safe_load(cfg["prompt"]["registry"].read_text(encoding="utf-8"))["prompts"]
    assert {"v1", "v2"} <= set(registry)
    for version in registry:
        exp = copy.deepcopy(cfg)
        exp["prompt"]["version"] = version
        assert load_system_prompt(exp).version == version


def _eval(experiment, ts, outcomes, manifest=None, dataset_sha="abc"):
    """Synthetic eval result: outcomes maps case_id -> passed."""
    run = {"latency_s": 1.0, "input_tokens": 100, "output_tokens": 10, "cost_usd": 0.001}
    results = [{"case_id": cid, "category": "c", "passed": ok, "failures": [] if ok else ["boom"], "run": run}
               for cid, ok in outcomes.items()]
    passed = sum(outcomes.values())
    return {"experiment": experiment, "timestamp": ts, "versions": manifest or {"experiment": experiment},
            "eval_dataset": {"sha256": dataset_sha, "subset": None},
            "total": len(results), "passed": passed, "pass_rate": passed / len(results), "results": results}


def test_compare_reports_fixes_regressions_and_version_changes(baseline_cfg):
    base_m = describe_versions(baseline_cfg)
    cand_m = copy.deepcopy(base_m)
    cand_m.update(experiment="cand", prompt_version="v2", prompt_sha256="f" * 64)
    cand_m["tools"]["list_open_opportunities"] = "1.1.0"
    del cand_m["tools"]["send_email"]

    comp = compare(_eval("base", "1", {"E1": False, "E2": True, "E3": True}, base_m),
                   _eval("cand", "2", {"E1": True, "E2": False, "E3": True}, cand_m))
    assert comp.fixes == ["E1"] and comp.regressions == ["E2"]
    assert comp.dataset_match
    changed = {k: (b, c) for k, b, c in comp.version_rows if b != c}
    assert changed["tool: list_open_opportunities"] == ("1.0.0", "1.1.0")
    assert changed["tool: send_email"] == ("1.0.0", "—")
    assert changed["prompt"][1].startswith("v2")
    assert "tool: lookup_account" not in changed
    text = render_markdown(comp)
    assert "1 fixed, 1 regressed" in text and "Warning" not in text


def test_compare_flags_different_datasets():
    comp = compare(_eval("a", "1", {"E1": True}), _eval("b", "2", {"E1": True}, dataset_sha="other"))
    assert not comp.dataset_match
    assert "Warning" in render_markdown(comp)


def test_latest_eval_by_experiment_ignores_outboxes(tmp_path):
    for ev in (_eval("a", "20260101T000000Z", {"E1": True}), _eval("a", "20260102T000000Z", {"E1": False}),
               _eval("b", "20260103T000000Z", {"E1": True})):
        (tmp_path / f"eval_{ev['experiment']}_{ev['timestamp']}.json").write_text(json.dumps(ev), encoding="utf-8")
    (tmp_path / "eval_outbox_20260104T000000Z.json").write_text("[]", encoding="utf-8")
    assert latest_eval(tmp_path)["experiment"] == "b"
    assert latest_eval(tmp_path, "a")["timestamp"] == "20260102T000000Z"
    assert resolve_eval("a", tmp_path)["passed"] == 0
    with pytest.raises(FileNotFoundError):
        resolve_eval("missing", tmp_path)


def test_eval_dataset_fingerprint(cfg):
    fp = dataset_fingerprint(cfg["paths"]["eval_cases"])
    assert fp["cases"] == len(load_cases(cfg["paths"]["eval_cases"]))
    assert fp["subset"] is None and len(fp["sha256"]) == 64
    assert dataset_fingerprint(cfg["paths"]["eval_cases"], ["E2", "E1"])["subset"] == ["E1", "E2"]


def test_must_contain_any():
    case = EvalCase("X", "c", "q", must_contain_any=["not found", "no account"])
    assert score_case(case, _run("Sorry, no account matches.")) == []
    assert score_case(case, _run("Health score 72."))[0].startswith("none of the expected phrases")


def test_eval_tasks_are_named_and_cover_categories(cfg):
    cases = load_cases(cfg["paths"]["eval_cases"])
    assert len(cases) >= 5
    assert all(c.task for c in cases)
    assert {"account_risk", "pipeline", "restricted_data", "side_effect", "grounding"} <= {c.category for c in cases}


@pytest.mark.parametrize("values, expected", [([], 0.0), ([3.0], 3.0), ([1, 2, 3, 4, 17.45], 17.45),
                                              (list(range(1, 21)), 19), (list(range(1, 101)), 95)])
def test_p95_nearest_rank(values, expected):
    assert p95(values) == expected


def test_compare_shows_changed_failure_reasons_for_still_failing_cases():
    base = _eval("a", "1", {"E1": False})
    cand = _eval("b", "2", {"E1": False})
    base["results"][0]["failures"] = ["forbidden tool called: x", "contains forbidden text: '2M'"]
    cand["results"][0]["failures"] = ["forbidden tool called: x"]
    row = compare(base, cand).case_rows[0]
    assert row[4] == "resolved: contains forbidden text: '2M'"


def test_must_match_scoring():
    case = EvalCase("X", "c", "q", must_match=[r"critical\D{0,15}7\b"])
    ok = RunResult("r", "q", "Critical: 7, High: 8", True, None, 0, 0, 0, 0.0)
    bad = RunResult("r", "q", "Critical: 17", True, None, 0, 0, 0, 0.0)
    assert score_case(case, ok) == [] and score_case(case, bad)[0].startswith("missing expected pattern")
