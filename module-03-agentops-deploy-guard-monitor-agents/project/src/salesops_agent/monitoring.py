"""Monitoring report: aggregate many agent / evaluation runs from logs/runs.jsonl.

`uv run generate-monitoring-report` writes reports/monitoring_report.md (for people)
and reports/monitoring_report.json (the same metrics, for tools/CI).

Definitions used throughout:
  - failed run    status "error", or an evaluation task that did not pass
  - succeeded run every other run. A guardrail block is a *successful* outcome when
                  it was the right thing to do (an evaluation task decides); blocks
                  are counted separately as interventions, not as failures
  - intervention  any guardrail (input / tool / sandbox / output) or approval-gate
                  action recorded on the run
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from salesops_agent.config import PROJECT_ROOT

SLOW_RUN_S = 30.0          # runs slower than this are called out (API stalls, retries)
TOP_N = 10


# -- loading ------------------------------------------------------------------------

def load_run_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def filter_runs(runs: Iterable[Dict[str, Any]], since: Optional[str] = None,
                experiments: Optional[List[str]] = None, source: str = "all") -> List[Dict[str, Any]]:
    out = []
    for run in runs:
        if since and run["timestamp"] < since:
            continue
        if experiments and run.get("experiment") not in experiments:
            continue
        kind = "eval" if str(run.get("source", "")).startswith("eval") else "cli"
        if source != "all" and kind != source:
            continue
        out.append(run)
    return out


# -- metrics --------------------------------------------------------------------------

def is_failed(run: Dict[str, Any]) -> bool:
    return run.get("status") == "error" or run.get("task_passed") is False


def percentile(values: List[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def normalize_failure(reason: str) -> str:
    """Group equivalent failure reasons: error type + message, or the failed check."""
    reason = reason.strip()
    m = re.match(r"^([A-Za-z_][\w.]*(Error|Exception|Timeout)):\s*(.*)$", reason)
    if m:
        return f"{m.group(1)}: {m.group(3)[:80]}"
    return reason[:160]


def compute_metrics(runs: List[Dict[str, Any]], filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    total = len(runs)
    failed = [r for r in runs if is_failed(r)]
    eval_runs = [r for r in runs if r.get("task_id")]
    latencies = [float(r.get("latency_s") or 0.0) for r in runs]
    costs = [float(r.get("cost_usd") or 0.0) for r in runs]

    executed = Counter(t for r in runs for t in r.get("tools_called", []))
    selected = Counter(t for r in runs for t in r.get("tools_selected", []))
    blocked: Dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        for b in r.get("tools_blocked", []):
            blocked[b["tool"]][b["reason"]] += 1

    by_stage: Counter = Counter()
    by_rule: Counter = Counter()
    for r in runs:
        for i in r.get("guardrail_interventions", []):
            by_stage[i["stage"]] += 1
            key = i.get("rule") or (", ".join(i["rules"]) if i.get("rules") else None) or i.get("reason") or i["action"]
            by_rule[(i["stage"], i["action"], key)] += 1
    guardrail_blocks = sum(n for (stage, action, _), n in by_rule.items() if action in ("block", "refuse", "review", "rejected"))

    decisions = Counter(d["decision"] for r in runs for d in (r.get("hitl") or {}).get("decisions", []))
    requests = sum(decisions.values())

    failure_counter: Counter = Counter()
    failure_examples: Dict[str, List[str]] = defaultdict(list)
    for r in failed:
        reasons = [r["error"]] if r.get("status") == "error" and r.get("error") else \
            [p for p in (r.get("failure_reason") or "unknown").split("; ") if p]
        for reason in reasons:
            key = normalize_failure(reason)
            failure_counter[key] += 1
            label = r.get("task_id") or r["run_id"]
            if label not in failure_examples[key] and len(failure_examples[key]) < 5:
                failure_examples[key].append(label)

    by_experiment = []
    for exp in sorted({r.get("experiment") for r in runs}, key=str):
        rs = [r for r in runs if r.get("experiment") == exp]
        lat = [float(r.get("latency_s") or 0.0) for r in rs]
        by_experiment.append({
            "experiment": exp,
            "runs": len(rs),
            "success_rate": _rate(len(rs) - sum(is_failed(r) for r in rs), len(rs)),
            "avg_latency_s": round(sum(lat) / len(lat), 3) if lat else 0.0,
            "p95_latency_s": percentile(lat, 0.95),
            "total_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rs), 6),
            "interventions": sum(len(r.get("guardrail_interventions", [])) for r in rs),
            "hitl_approved": sum(1 for r in rs for d in (r.get("hitl") or {}).get("decisions", []) if d["decision"] == "approved"),
            "hitl_rejected": sum(1 for r in rs for d in (r.get("hitl") or {}).get("decisions", []) if d["decision"] == "rejected"),
        })

    metrics = {
        "monitoring_report_schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filters": filters or {},
        "window": {"first_run": min((r["timestamp"] for r in runs), default=None),
                   "last_run": max((r["timestamp"] for r in runs), default=None)},
        "total_runs": total,
        "runs_by_source": dict(Counter("eval" if str(r.get("source", "")).startswith("eval") else "cli" for r in runs)),
        "outcomes": {
            "succeeded": total - len(failed),
            "failed": len(failed),
            "success_rate": _rate(total - len(failed), total),
            "failure_rate": _rate(len(failed), total),
            "errors": sum(1 for r in runs if r.get("status") == "error"),
            "eval_runs": len(eval_runs),
            "eval_passed": sum(1 for r in eval_runs if r.get("task_passed")),
            "eval_pass_rate": _rate(sum(1 for r in eval_runs if r.get("task_passed")), len(eval_runs)),
        },
        "status_counts": dict(Counter(r.get("status") for r in runs).most_common()),
        "latency_s": {
            "average": round(sum(latencies) / total, 3) if total else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies, default=0.0),
            "slow_runs_over_30s": sum(1 for x in latencies if x > SLOW_RUN_S),
        },
        "cost": {
            "total_usd": round(sum(costs), 6),
            "average_per_run_usd": round(sum(costs) / total, 6) if total else 0.0,
            "input_tokens": sum(int(r.get("input_tokens") or 0) for r in runs),
            "output_tokens": sum(int(r.get("output_tokens") or 0) for r in runs),
            "model_free_runs": sum(1 for r in runs if not r.get("input_tokens")),
        },
        "tools": {
            "calls_executed": dict(executed.most_common()),
            "calls_selected_by_model": dict(selected.most_common()),
            "calls_blocked": {tool: dict(reasons.most_common()) for tool, reasons in
                              sorted(blocked.items(), key=lambda kv: -sum(kv[1].values()))},
            "total_executed": sum(executed.values()),
            "total_blocked": sum(sum(c.values()) for c in blocked.values()),
        },
        "guardrails": {
            "total_interventions": sum(by_stage.values()),
            "blocks": guardrail_blocks,
            "runs_with_intervention": sum(1 for r in runs if r.get("guardrail_interventions")),
            "by_stage": dict(by_stage.most_common()),
            "by_rule": [{"stage": s, "action": a, "rule": k, "count": n} for (s, a, k), n in by_rule.most_common(TOP_N)],
        },
        "hitl": {
            "approval_requests": requests,
            "approved": decisions.get("approved", 0),
            "rejected": decisions.get("rejected", 0),
            "pending": decisions.get("pending", 0),
            "approval_rate": _rate(decisions.get("approved", 0), requests),
        },
        "failure_reasons": [{"reason": k, "count": n, "examples": failure_examples[k]}
                            for k, n in failure_counter.most_common(TOP_N)],
        "by_experiment": by_experiment,
    }
    metrics["observations"] = observations(metrics)
    return metrics


def observations(m: Dict[str, Any]) -> List[str]:
    """Plain-language reading of the numbers, for the report's Interpretation section."""
    notes = []
    o, lat, g, h = m["outcomes"], m["latency_s"], m["guardrails"], m["hitl"]
    if not m["total_runs"]:
        return ["No runs in the selected window."]
    if o["failed"]:
        top = m["failure_reasons"][0] if m["failure_reasons"] else None
        notes.append(f"{o['failed']} of {m['total_runs']} runs failed ({o['failure_rate']:.0%})"
                     + (f"; the most common reason is \"{top['reason']}\" ({top['count']}x, e.g. "
                        f"{', '.join(top['examples'][:3])})." if top else "."))
    else:
        notes.append(f"All {m['total_runs']} runs succeeded.")
    if o["errors"]:
        notes.append(f"{o['errors']} run(s) ended in an error (exception or API failure); inspect them with "
                     "`salesops-agent runs --failed`.")
    if lat["slow_runs_over_30s"]:
        notes.append(f"{lat['slow_runs_over_30s']} run(s) took over {SLOW_RUN_S:.0f}s (max {lat['max']:.0f}s) while the "
                     f"median is {lat['p50']:.1f}s: latency outliers, typically a stalled API call that hit the "
                     "request timeout and was retried.")
    if g["total_interventions"]:
        top_rule = g["by_rule"][0]
        notes.append(f"Runtime controls intervened in {g['runs_with_intervention']} run(s) "
                     f"({g['total_interventions']} interventions; by stage: "
                     + ", ".join(f"{s} {n}" for s, n in g["by_stage"].items())
                     + f"). Most frequent: {top_rule['stage']} {top_rule['action']} by `{top_rule['rule']}` "
                       f"({top_rule['count']}x).")
    if h["approval_requests"]:
        notes.append(f"{h['approval_requests']} high-risk action(s) required human approval: {h['approved']} approved, "
                     f"{h['rejected']} rejected, {h['pending']} left pending (not executed).")
    if m["cost"]["model_free_runs"]:
        notes.append(f"{m['cost']['model_free_runs']} run(s) made no model call (blocked by the input guardrail or "
                     "control probes), so they cost nothing.")
    weak = [e for e in m["by_experiment"] if e["runs"] >= 5 and e["success_rate"] < 0.9]
    if weak:
        notes.append("Experiments below 90% success: "
                     + ", ".join(f"{e['experiment']} ({e['success_rate']:.0%})" for e in weak) + ".")
    return notes


# -- rendering ----------------------------------------------------------------------------

def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(m: Dict[str, Any]) -> str:
    o, lat, cost, tools, g, h = m["outcomes"], m["latency_s"], m["cost"], m["tools"], m["guardrails"], m["hitl"]
    f = m["filters"]
    scope = ", ".join(f"{k}={v}" for k, v in f.items() if v and k != "runs_log") or "all runs"
    first, last = (m["window"]["first_run"] or "-")[:19], (m["window"]["last_run"] or "-")[:19]
    lines = [
        "# Monitoring Report",
        "",
        f"Generated {m['generated_at']} from `{f.get('runs_log', 'logs/runs.jsonl')}` ({scope}). "
        f"Window: {first} to {last} UTC.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total runs | {m['total_runs']} ({', '.join(f'{k} {v}' for k, v in m['runs_by_source'].items()) or '-'}) |",
        f"| Success rate | {o['success_rate']:.1%} ({_n(o['succeeded'], 'run')}) |",
        f"| Failure rate | {o['failure_rate']:.1%} ({_n(o['failed'], 'run')}, of which {_n(o['errors'], 'error')}) |",
        f"| Evaluation pass rate | {o['eval_pass_rate']:.1%} ({o['eval_passed']}/{o['eval_runs']} task runs) |",
        f"| Average latency | {lat['average']:.2f}s (p50 {lat['p50']:.2f}s, p95 {lat['p95']:.2f}s, max {lat['max']:.2f}s) |",
        f"| Estimated total cost | ${cost['total_usd']:.4f} ({cost['input_tokens']:,} input + {cost['output_tokens']:,} output tokens) |",
        f"| Estimated average cost per run | ${cost['average_per_run_usd']:.6f} |",
        f"| Tool calls | {tools['total_executed']} executed, {tools['total_blocked']} blocked |",
        f"| Guardrail blocks | {g['blocks']} ({g['total_interventions']} interventions in {g['runs_with_intervention']} runs) |",
        f"| HITL approvals | {h['approved']} |",
        f"| HITL rejections | {h['rejected']} (plus {h['pending']} pending, never executed) |",
        "",
        "## Interpretation",
        "",
        *[f"- {note}" for note in m["observations"]],
        "",
        "## Run outcomes",
        "",
        "| Status | Runs |",
        "|---|---|",
        *[f"| {s} | {n} |" for s, n in m["status_counts"].items()],
        "",
        "A run **failed** if it ended in an error or failed its evaluation task. Guardrail blocks are counted as "
        "interventions, not failures: blocking a restricted request is the correct outcome.",
        "",
        "## Common failure reasons",
        "",
    ]
    if m["failure_reasons"]:
        lines += ["| Reason | Count | Examples (task or run id) |", "|---|---|---|"]
        lines += [f"| {_md(fr['reason'])} | {fr['count']} | {', '.join(fr['examples'])} |" for fr in m["failure_reasons"]]
    else:
        lines.append("No failed runs.")
    lines += [
        "",
        "## Tool calls",
        "",
        "| Tool | Executed | Selected by model | Blocked (reason: count) |",
        "|---|---|---|---|",
    ]
    names = list(dict.fromkeys([*tools["calls_executed"], *tools["calls_selected_by_model"], *tools["calls_blocked"]]))
    for name in names:
        blocked = ", ".join(f"{r}: {n}" for r, n in tools["calls_blocked"].get(name, {}).items()) or "-"
        lines.append(f"| `{name}` | {tools['calls_executed'].get(name, 0)} | "
                     f"{tools['calls_selected_by_model'].get(name, 0)} | {blocked} |")
    lines += [
        "",
        "## Guardrail interventions",
        "",
        "| Stage | Interventions |",
        "|---|---|",
        *[f"| {s} | {n} |" for s, n in g["by_stage"].items()],
        "",
        "Most frequent rules:",
        "",
        "| Stage | Action | Rule / reason | Count |",
        "|---|---|---|---|",
        *[f"| {r['stage']} | {r['action']} | `{_md(r['rule'])}` | {r['count']} |" for r in g["by_rule"]],
        "",
        "## Human-in-the-loop",
        "",
        "| Approval requests | Approved | Rejected | Pending | Approval rate |",
        "|---|---|---|---|---|",
        f"| {h['approval_requests']} | {h['approved']} | {h['rejected']} | {h['pending']} | {h['approval_rate']:.0%} |",
        "",
        "## By experiment",
        "",
        "| Experiment | Runs | Success rate | Avg latency | p95 latency | Total cost | Interventions | HITL approved / rejected |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {e['experiment']} | {e['runs']} | {e['success_rate']:.0%} | {e['avg_latency_s']:.2f}s | "
          f"{e['p95_latency_s']:.2f}s | ${e['total_cost_usd']:.4f} | {e['interventions']} | "
          f"{e['hitl_approved']} / {e['hitl_rejected']} |" for e in m["by_experiment"]],
        "",
        "Drill down: `uv run salesops-agent runs --failed`, `uv run salesops-agent inspect <run_id>`.",
        "",
    ]
    return "\n".join(lines)


def write_monitoring_report(runs_log: Path, output: Path, since: Optional[str] = None,
                            experiments: Optional[List[str]] = None, source: str = "all") -> Tuple[Path, Path, Dict]:
    runs = filter_runs(load_run_records(runs_log), since=since, experiments=experiments, source=source)
    try:
        shown = runs_log.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        shown = runs_log.as_posix()
    filters = {"runs_log": shown, "since": since, "experiments": ", ".join(experiments or []) or None,
               "source": None if source == "all" else source}
    metrics = compute_metrics(runs, filters)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(metrics), encoding="utf-8")
    json_path = output.with_suffix(".json")
    json_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return output, json_path, metrics
