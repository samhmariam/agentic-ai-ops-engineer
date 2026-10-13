"""CLI entry point tests (`salesops-agent`). Offline: the agent graph is faked."""

import json

import pytest
from click.testing import CliRunner
from langchain_core.messages import AIMessage

from salesops_agent import cli, runner
from salesops_agent.agent import SalesOpsAgent, describe_versions
from salesops_agent.config import DEFAULT_CONFIG_PATH, load_config


class FakeGraph:
    def __init__(self, answer="Fake answer about TechStart.", error=None):
        self.answer, self.error, self.calls = answer, error, []

    def invoke(self, payload, config=None):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return {"messages": [*payload["messages"], AIMessage(content=self.answer)]}


@pytest.fixture
def tmp_config(tmp_path):
    """Experiment config that extends the real one but writes artifacts into tmp_path."""
    path = tmp_path / "test.yaml"
    path.write_text(
        f"extends: {DEFAULT_CONFIG_PATH.as_posix()}\n"
        "experiment: {name: cli-test}\n"
        "paths: {logs_dir: logs, traces_dir: traces, reports_dir: reports}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def fake_agent(monkeypatch, tmp_config):
    graph = FakeGraph()
    agent = SalesOpsAgent(graph=graph, manifest=describe_versions(load_config(tmp_config)))
    monkeypatch.setattr(runner, "build_agent", lambda cfg: agent)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return graph


def invoke(*args):
    return CliRunner().invoke(cli.app, list(args))


def test_ask_prints_answer_and_writes_log_and_trace(fake_agent, tmp_config, tmp_path):
    result = invoke("ask", "Summarize the account risk for TechStart Inc.", "--config", str(tmp_config))
    assert result.exit_code == 0, result.output
    assert "Fake answer about TechStart." in result.stdout
    assert "[trace:" in result.stderr and "[log:" in result.stderr
    assert fake_agent.calls[0]["messages"][0]["content"] == "Summarize the account risk for TechStart Inc."

    events = [json.loads(line) for line in (tmp_path / "logs" / "agent.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["run_started", "run_completed"]
    assert events[0]["versions"]["prompt_version"] == "v2"
    assert events[0]["versions"]["guardrails"]["input"]["enabled"] is True
    assert events[1]["experiment"] == "cli-test" and events[1]["success"] is True
    assert "question" not in events[1] and "answer" not in events[1]   # no raw text in logs

    trace = json.loads(next((tmp_path / "traces").glob("*.json")).read_text())
    assert trace["run_id"] == events[1]["run_id"]
    assert trace["answer"] == "Fake answer about TechStart."
    assert trace["versions"]["experiment"] == "cli-test"


def test_ask_json_output(fake_agent, tmp_config):
    result = invoke("ask", "Hi", "--config", str(tmp_config), "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["answer"] == "Fake answer about TechStart." and data["success"] is True


def test_ask_run_failure_exits_nonzero_with_trace(fake_agent, tmp_config):
    fake_agent.error = RuntimeError("model unavailable")
    result = invoke("ask", "Hi", "--config", str(tmp_config))
    assert result.exit_code == 1
    assert "failed: RuntimeError: model unavailable" in result.output and "trace:" in result.output


def test_ask_rejects_empty_question(fake_agent, tmp_config):
    result = invoke("ask", "   ", "--config", str(tmp_config))
    assert result.exit_code == 2 and "must not be empty" in result.output


def test_ask_without_api_key_gives_clear_error(monkeypatch, tmp_config):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = invoke("ask", "Hi", "--config", str(tmp_config))
    assert result.exit_code == 1
    assert "OPENAI_API_KEY is not set" in result.output
    assert "Traceback" not in result.output


def test_bad_config_gives_clear_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(f"extends: {DEFAULT_CONFIG_PATH.as_posix()}\nmodel: {{temperature: 9}}\n", encoding="utf-8")
    result = invoke("versions", "--config", str(bad))
    assert result.exit_code == 1 and "Invalid config" in result.output


def test_versions_and_help():
    out = invoke("versions").output
    assert "prompt v2" in out and "input guardrail policy v1" in out
    help_text = invoke("--help").output
    for command in ("ask", "eval", "compare", "experiments", "report", "versions"):
        assert command in help_text


@pytest.fixture
def fake_eval_agent(monkeypatch, tmp_config):
    from salesops_agent import evaluation

    graph = FakeGraph(answer="I could not find an account named Quantum Pickle Logistics.")
    agent = SalesOpsAgent(graph=graph, manifest=describe_versions(load_config(tmp_config)))
    monkeypatch.setattr(evaluation, "build_agent", lambda cfg: agent)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return graph


def run_evaluate(*args):
    return CliRunner().invoke(cli.evaluate, list(args))


def test_evaluate_prints_per_task_metrics_and_writes_reports(fake_eval_agent, tmp_config, tmp_path):
    result = run_evaluate("--config", str(tmp_config), "--case", "E012", "--case", "E004")
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "PASS  E012" in out                                   # unknown account admitted
    assert "FAIL  E004" in out and "expected tool not called: lookup_account" in out
    assert "s  $0." in out and "1/2 passed (50%)" in out

    reports = tmp_path / "reports"
    md, csv_text = (reports / "evaluation_report.md").read_text(), (reports / "evaluation_report.csv").read_text()
    data = json.loads((reports / "evaluation_report.json").read_text())

    header, *rows = csv_text.strip().splitlines()
    assert header.split(",")[:4] == ["task_id", "task", "category", "status"]
    assert {"latency_s", "cost_usd", "failure_reason"} <= set(header.split(","))
    assert len(rows) == 2
    assert data["passed"] == 1 and data["experiment"] == "cli-test"
    assert {t["task_id"]: t["status"] for t in data["tasks"]} == {"E004": "FAIL", "E012": "PASS"}
    assert set(data["totals"]) >= {"latency_s_total", "latency_s_avg", "cost_usd"}
    assert "| Tasks passed | 1/2 (50%) |" in md and "## Failures" in md and "Failure reason" in md
    assert list(reports.glob("eval_cli-test_*.json"))             # history file for compare


def test_evaluate_min_pass_rate_gate(fake_eval_agent, tmp_config):
    result = run_evaluate("--config", str(tmp_config), "--case", "E004", "--min-pass-rate", "0.5")
    assert result.exit_code == 1 and "Pass rate below 50%" in result.output


def test_eval_subcommand_matches_evaluate(fake_eval_agent, tmp_config):
    result = invoke("eval", "--config", str(tmp_config), "--case", "E012")
    assert result.exit_code == 0 and "PASS  E012" in result.stdout
