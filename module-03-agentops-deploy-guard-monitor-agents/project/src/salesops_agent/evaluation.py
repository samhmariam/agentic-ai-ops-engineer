"""Evaluation harness.

Runs each task in evaluation/eval_cases.jsonl through `run_question` and scores it
with deterministic checks:
  - expected_tools:   each must be called at least once
  - forbidden_tools:  none may be called
  - must_contain:     each substring must appear in the answer (case-insensitive)
  - must_contain_any: at least one of these substrings must appear (case-insensitive)
  - must_not_contain: no substring may appear in the answer (case-insensitive)
Every failed check becomes a failure reason. Latency, tokens and estimated cost
come from the run itself (runner.py).

Emails sent during evaluation go to a throwaway outbox under reports/, never to the
real data/email_outbox.json. Results are written to
reports/eval_<experiment>_<timestamp>.json with the full version manifest and the
eval dataset fingerprint, so `salesops compare` can diff any two experiments, and
the latest run is also written as reports/evaluation_report.{md,csv,json}.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional

from salesops_agent.agent import build_agent
from salesops_agent.config import ensure_output_dirs, with_overrides
from salesops_agent.reporting import write_evaluation_report
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


@dataclass
class CaseResult:
    case_id: str
    category: str
    passed: bool
    failures: List[str]
    run: dict
    task: str = ""


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
    return failures


def run_evaluation(
    cfg: dict[str, Any],
    case_ids: Optional[List[str]] = None,
    on_result: Optional[Callable[[CaseResult], None]] = None,
) -> EvaluationOutput:
    ensure_output_dirs(cfg)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    eval_cfg = with_overrides(
        cfg, email_outbox=cfg["paths"]["reports_dir"] / f"eval_outbox_{stamp}.json"
    )
    cases = load_cases(cfg["paths"]["eval_cases"], case_ids)
    agent = build_agent(eval_cfg)

    results: List[CaseResult] = []
    for case in cases:
        run = run_question(eval_cfg, case.question, source=f"eval:{case.id}", agent=agent)
        failures = score_case(case, run)
        result = CaseResult(case_id=case.id, category=case.category, passed=not failures,
                            failures=failures, run=run.to_dict(), task=case.task)
        results.append(result)
        if on_result:
            on_result(result)

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
        "latency_s_p95": latencies[min(n - 1, round(0.95 * (n - 1)))] if n else 0.0,
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
