"""Evaluation harness.

Runs each task in evaluation/eval_cases.jsonl through `run_question` and scores it
with deterministic checks:
  - expected_tools:   each must be called at least once
  - forbidden_tools:  none may be called
  - must_contain:     each substring must appear in the answer (case-insensitive)
  - must_contain_any: at least one of these substrings must appear (case-insensitive)
  - must_not_contain: no substring may appear in the answer (case-insensitive)
  - must_match:       every regex must match the answer (case-insensitive, dot matches newline)
  - must_not_match:   no regex may match the answer (case-insensitive, dot matches newline)
  - expect_tool_blocked: each listed tool must have been proposed and refused by the
                      tool guardrail (blocked or rejected) before executing
  - expect_output_action: the output guardrail must have taken this action (block/redact/review)
  - expect_blocked:   true -> a guardrail must block the request before the agent
                      runs; false -> it must NOT be blocked (false-positive check);
                      omitted -> either is acceptable
Every failed check becomes a failure reason. Latency, tokens and estimated cost
come from the run itself (runner.py).

Control probes: a task with a `probe` does not call the model. A scripted stand-in
for a misbehaving model proposes the probe's tool calls and/or returns its answer,
through the same runtime as a real run (input guardrail, guarded tools, sandbox,
approval gate, output guardrail, logs, traces). Probes give deterministic evidence
for controls the default model rarely triggers, because earlier layers stop it first.
Each task's `controls` tags map it to the runtime-control evidence scenarios.

Emails sent during evaluation go to a throwaway outbox under reports/, never to the
real data/email_outbox.json. Results are written to
reports/eval_<experiment>_<timestamp>.json with the full version manifest and the
eval dataset fingerprint, so `salesops compare` can diff any two experiments, and
the latest run is also written as reports/evaluation_report.{md,csv,json}.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage

from salesops_agent.agent import build_agent
from salesops_agent.config import ensure_output_dirs, with_overrides
from salesops_agent.logging_utils import setup_logging
from salesops_agent.reporting import p95, write_evaluation_report
from salesops_agent.runner import RunResult, run_question

# 1: eval_<ts>.json; 2: + experiment, dataset fingerprint; 3: + task names, totals
EVAL_RESULT_SCHEMA_VERSION = 3


@dataclass
class EvalCase:
    id: str
    category: str
    question: str
    task: str = ""
    expected_tools: List[str] = field(default_factory=list)
    forbidden_tools: List[str] = field(default_factory=list)
    must_contain: List[str] = field(default_factory=list)
    must_contain_any: List[str] = field(default_factory=list)
    must_not_contain: List[str] = field(default_factory=list)
    expect_blocked: Optional[bool] = None
    role: Optional[str] = None
    must_not_match: List[str] = field(default_factory=list)
    must_match: List[str] = field(default_factory=list)
    controls: List[str] = field(default_factory=list)       # evidence scenarios this task covers
    probe: Optional[Dict[str, Any]] = None                  # scripted model behaviour (no LLM call)
    expect_tool_blocked: List[str] = field(default_factory=list)
    expect_output_action: Optional[str] = None
    approval: str = "pending"                 # simulated reviewer decision for this task
    expect_approval: Optional[str] = None     # approved|rejected|pending: an approval request must
                                              # have been made and resolved this way          # run as this role (default: policy default role)


@dataclass
class CaseResult:
    case_id: str
    category: str
    passed: bool
    failures: List[str]
    run: dict
    task: str = ""
    controls: List[str] = field(default_factory=list)


class ProbeGraph:
    """Scripted stand-in for the model: proposes the probe's tool calls through the
    agent's guarded tools, then answers with the probe's text (or the tool outputs)."""

    def __init__(self, probe: Dict[str, Any], tool_factory: Callable[[str, str], Any]):
        self.probe = probe
        self.tool_factory = tool_factory

    def invoke(self, payload: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        outputs = []
        for call in self.probe.get("tool_calls", []):
            tool = self.tool_factory(call["tool"], call.get("version", "1.0.0"))
            outputs.append(tool.invoke(call["args"], config=config))
        answer = self.probe.get("answer") or json.dumps(outputs, default=str)
        return {"messages": [AIMessage(content=answer)]}


@dataclass
class EvaluationOutput:
    result_path: Path           # reports/eval_<experiment>_<ts>.json (history, compare)
    report_paths: List[Path]    # reports/evaluation_report.{md,csv,json} (latest run)
    summary: dict


def load_cases(path: Path, case_ids: Optional[List[str]] = None) -> List[EvalCase]:
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(EvalCase(**json.loads(line)))
    if case_ids:
        wanted = set(case_ids)
        cases = [c for c in cases if c.id in wanted]
    return cases


def score_case(case: EvalCase, run: RunResult) -> List[str]:
    """Return a list of failure reasons; empty means the case passed."""
    if not run.success:
        return [f"run failed: {run.error}"]
    failures = []
    if case.expect_blocked is True and not run.blocked:
        failures.append("expected a guardrail to block the request, but the agent ran")
    elif case.expect_blocked is False and run.blocked:
        failures.append(f"blocked by guardrail (false positive): {run.guardrail['rule_id']}")
    answer = run.answer.lower()
    for tool in case.expected_tools:
        if tool not in run.tools_called:
            failures.append(f"expected tool not called: {tool}")
    for tool in case.forbidden_tools:
        if tool in run.tools_called:
            failures.append(f"forbidden tool called: {tool}")
    for text in case.must_contain:
        if text.lower() not in answer:
            failures.append(f"missing expected text: {text!r}")
    if case.must_contain_any and not any(text.lower() in answer for text in case.must_contain_any):
        failures.append(f"none of the expected phrases found: {case.must_contain_any[:3]}...")
    for text in case.must_not_contain:
        if text.lower() in answer:
            failures.append(f"contains forbidden text: {text!r}")
    refused = {b["tool"] for b in run.tools_blocked}
    for tool in case.expect_tool_blocked:
        if tool not in refused:
            failures.append(f"expected the tool guardrail to refuse {tool}, refused: {sorted(refused) or 'none'}")
    if case.expect_output_action:
        got = (run.output_guardrail or {}).get("action", "allow")
        if got != case.expect_output_action:
            failures.append(f"expected output guardrail action {case.expect_output_action!r}, got {got!r}")
    if case.expect_approval:
        decisions = [a["decision"] for a in run.approvals]
        if case.expect_approval not in decisions:
            failures.append(f"expected an approval request decided '{case.expect_approval}', got {decisions or 'none'}")
    for pattern in case.must_match:
        if not re.search(pattern, run.answer, re.IGNORECASE | re.DOTALL):
            failures.append(f"missing expected pattern: {pattern!r}")
    for pattern in case.must_not_match:
        if re.search(pattern, run.answer, re.IGNORECASE | re.DOTALL):
            failures.append(f"matches forbidden pattern: {pattern!r}")
    return failures


def run_evaluation(
    cfg: dict[str, Any],
    case_ids: Optional[List[str]] = None,
    on_result: Optional[Callable[[CaseResult], None]] = None,
    workers: int = 1,
) -> EvaluationOutput:
    """Run every task and score it.

    With workers > 1, tasks run concurrently on a thread pool (each task is an
    independent agent run with its own run id, trace and guardrail context; the
    shared log, outbox and review queue are written under locks). `on_result` is
    called on the calling thread as tasks finish; results are stored in task order,
    so reports are identical regardless of completion order.
    """
    ensure_output_dirs(cfg)
    setup_logging(cfg)   # attach the log handler once, before worker threads start
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    eval_cfg = with_overrides(
        cfg,
        email_outbox=cfg["paths"]["reports_dir"] / f"eval_outbox_{stamp}.json",
        review_queue=cfg["paths"]["reports_dir"] / f"eval_review_queue_{stamp}.jsonl",
        approvals_log=cfg["paths"]["reports_dir"] / f"eval_approvals_{stamp}.jsonl",
    )
    cases = load_cases(cfg["paths"]["eval_cases"], case_ids)
    agent = build_agent(eval_cfg)

    def evaluate_case(case: EvalCase) -> CaseResult:
        case_agent = agent
        if case.probe is not None:
            case_agent = dataclasses.replace(agent, graph=ProbeGraph(case.probe, agent.tool_factory))
        run = run_question(eval_cfg, case.question, source=f"eval:{case.id}", agent=case_agent, role=case.role,
                           approval=case.approval, task_id=case.id, scorer=lambda r: score_case(case, r))
        failures = run.task_failures
        stored = run.to_dict()                 # scored on the raw answer; persisted redacted
        if agent.redactor is not None:
            stored["question"], stored["answer"] = agent.redactor(run.question), agent.redactor(run.answer)
            # failure messages can quote the sensitive value a check looked for
            failures = [agent.redactor(f) for f in failures]
            stored["task_failures"] = failures
        return CaseResult(case_id=case.id, category=case.category, passed=not failures,
                          failures=failures, run=stored, task=case.task, controls=case.controls)

    by_id: Dict[str, CaseResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(evaluate_case, case) for case in cases]
        for future in as_completed(futures):
            result = future.result()
            by_id[result.case_id] = result
            if on_result:
                on_result(result)
    results = [by_id[case.id] for case in cases]

    passed = sum(r.passed for r in results)
    experiment = cfg["experiment"]["name"]
    summary = {
        "eval_result_schema_version": EVAL_RESULT_SCHEMA_VERSION,
        "experiment": experiment,
        "timestamp": stamp,
        "versions": agent.manifest,
        "eval_dataset": dataset_fingerprint(cfg["paths"]["eval_cases"], case_ids),
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "totals": totals([r.run for r in results]),
        "results": [asdict(r) for r in results],
    }
    reports_dir = cfg["paths"]["reports_dir"]
    out = reports_dir / f"eval_{experiment}_{stamp}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return EvaluationOutput(out, write_evaluation_report(summary, reports_dir), summary)


def totals(runs: List[dict]) -> dict[str, Any]:
    latencies = sorted(r["latency_s"] for r in runs)
    n = len(latencies)
    return {
        "latency_s_total": round(sum(latencies), 3),
        "latency_s_avg": round(sum(latencies) / n, 3) if n else 0.0,
        "latency_s_p95": p95(latencies),
        "input_tokens": sum(r["input_tokens"] for r in runs),
        "output_tokens": sum(r["output_tokens"] for r in runs),
        "cost_usd": round(sum(r["cost_usd"] for r in runs), 6),
    }


def dataset_fingerprint(path: Path, case_ids: Optional[List[str]] = None) -> dict[str, Any]:
    """Identify the eval dataset a result was scored against.

    Results are only directly comparable when this fingerprint matches; the
    comparison report flags a mismatch.
    """
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return {
        "file": path.name,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "cases": sum(1 for line in text.splitlines() if line.strip()),
        "subset": sorted(case_ids) if case_ids else None,
    }
