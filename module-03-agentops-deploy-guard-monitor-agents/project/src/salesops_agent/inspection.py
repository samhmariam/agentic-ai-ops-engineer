"""Reading run logs and traces back for review: `salesops-agent runs` and `inspect`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

FAILED_STATUSES = {"error", "blocked_by_input_guardrail", "output_blocked", "output_withheld_for_review"}


def load_runs(runs_log: Path) -> List[Dict[str, Any]]:
    if not runs_log.exists():
        return []
    return [json.loads(line) for line in runs_log.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_failed(run: Dict[str, Any]) -> bool:
    """A run needs review if it errored, failed its evaluation task, or a control stopped it."""
    return run["status"] == "error" or run.get("task_passed") is False


def is_intervened(run: Dict[str, Any]) -> bool:
    return bool(run.get("guardrail_interventions")) or run["status"] in FAILED_STATUSES


def select_runs(runs: Iterable[Dict[str, Any]], failed: bool = False, intervened: bool = False,
                task_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    out = [r for r in runs
           if (not failed or is_failed(r)) and (not intervened or is_intervened(r))
           and (task_id is None or r.get("task_id") == task_id)]
    return out[-limit:]


def find_run(runs: List[Dict[str, Any]], run_id: str) -> Optional[Dict[str, Any]]:
    matches = [r for r in runs if r["run_id"].startswith(run_id)]
    return matches[-1] if matches else None


def format_run_line(run: Dict[str, Any]) -> str:
    interventions = ", ".join(
        f"{i['stage']}:{i.get('reason') or i.get('rule') or i['action']}" for i in run.get("guardrail_interventions", [])
    )
    task = f" {run['task_id']}" if run.get("task_id") else ""
    verdict = {True: " PASS", False: " FAIL"}.get(run.get("task_passed"), "")
    return (f"{run['run_id']}  {run['timestamp'][:19]}  {run['experiment']:<16}{task}{verdict}  "
            f"{run['status']:<27} {run['latency_s']:6.2f}s  ${run['cost_usd']:.5f}  "
            f"tools={','.join(run['tools_called']) or '-'}"
            + (f"  hitl={run['hitl_decision']}" if run.get("hitl_decision") else "")
            + (f"  [{interventions}]" if interventions else ""))


def format_trace(trace: Dict[str, Any]) -> str:
    """Human-readable debugging view of one trace: summary, then the trajectory."""
    lines = [
        f"run {trace['run_id']}  ({trace.get('experiment') or trace.get('versions', {}).get('experiment')})",
        f"  status:         {trace.get('status')}" + (f"   task {trace['task_id']}: "
                                                       f"{'PASS' if trace.get('task_passed') else 'FAIL'}"
                                                       if trace.get("task_id") else ""),
        f"  input:          {trace.get('user_input')}",
        f"  final output:   {(trace.get('final_output') or '')[:300]}",
    ]
    if trace.get("error"):
        lines.append(f"  error:          {trace['error']}")
    if trace.get("failure_reason"):
        lines.append(f"  failure reason: {trace['failure_reason']}")
    lines.append(f"  latency/cost:   {trace.get('latency_s')}s, ${trace.get('cost_usd')}, "
                 f"tokens {trace.get('token_usage', {}).get('input_tokens')}+{trace.get('token_usage', {}).get('output_tokens')}")
    lines.append(f"  hitl:           {trace.get('hitl_decision') or 'not required'}")
    lines.append("  trajectory:")
    for span in trace.get("spans", []):
        kind, name = span["kind"], span["name"]
        detail = ""
        if kind == "llm":
            calls = span.get("requested_tool_calls") or []
            detail = "selects " + ", ".join(f"{c['name']}({c['args']})" for c in calls) if calls else "answers"
        elif kind == "tool":
            detail = f"args {span.get('input')} -> {span.get('output', span.get('error', ''))}"
        elif kind == "guardrail":
            detail = " ".join(str(span[k]) for k in ("rule_id", "rule_ids", "tool", "reason", "category")
                              if span.get(k))
        elif kind == "approval":
            detail = f"{span['tool']} approval requested -> {span['decision']} ({span['decided_by']})"
        lines.append(f"    {span['start_time'][11:23]}  {kind:<9} {name:<26} {span.get('status', ''):<10} "
                     f"{span.get('duration_ms', 0):>8.1f}ms  {detail[:220]}")
    return "\n".join(lines)
