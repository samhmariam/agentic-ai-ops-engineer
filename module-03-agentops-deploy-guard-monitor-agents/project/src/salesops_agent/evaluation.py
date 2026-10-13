"""Evaluation harness.

Runs each case in evaluation/eval_cases.jsonl through `run_question` and scores it
with deterministic checks:
  - expected_tools:   each must be called at least once
  - forbidden_tools:  none may be called
  - must_contain:     each substring must appear in the answer (case-insensitive)
  - must_not_contain: no substring may appear in the answer (case-insensitive)

Emails sent during evaluation go to a throwaway outbox under reports/, never to the
real data/email_outbox.json. Results are written to reports/eval_<timestamp>.json
for the reporting step and for comparison across prompt/tool versions.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional

from salesops_agent.agent import build_agent
from salesops_agent.config import ensure_output_dirs, with_overrides
from salesops_agent.runner import RunResult, run_question


@dataclass
class EvalCase:
    id: str
    category: str
    question: str
    expected_tools: List[str] = field(default_factory=list)
    forbidden_tools: List[str] = field(default_factory=list)
    must_contain: List[str] = field(default_factory=list)
    must_not_contain: List[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    category: str
    passed: bool
    failures: List[str]
    run: dict


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
    for text in case.must_not_contain:
        if text.lower() in answer:
            failures.append(f"contains forbidden text: {text!r}")
    return failures


def run_evaluation(
    cfg: dict[str, Any],
    case_ids: Optional[List[str]] = None,
    on_result: Optional[Callable[[CaseResult], None]] = None,
) -> Path:
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
        result = CaseResult(case.id, case.category, not failures, failures, run.to_dict())
        results.append(result)
        if on_result:
            on_result(result)

    passed = sum(r.passed for r in results)
    summary = {
        "timestamp": stamp,
        "agent_version": cfg["agent"]["version"],
        "prompt_version": cfg["prompt"]["version"],
        "model": cfg["model"]["name"],
        "tools_enabled": cfg["tools"]["enabled"],
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "results": [asdict(r) for r in results],
    }
    out = cfg["paths"]["reports_dir"] / f"eval_{stamp}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return out
