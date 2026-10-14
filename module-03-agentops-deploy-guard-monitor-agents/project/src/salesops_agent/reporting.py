"""Report generation.

Combines run telemetry from logs/ (all `run_completed` events) with the latest
evaluation result from reports/ into a Markdown report at reports/report_<experiment>_<ts>.md,
and writes the evaluation report (reports/evaluation_report.{md,csv,json}).
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from salesops_agent.versions import short_manifest


def load_run_events(log_path: Path) -> List[Dict[str, Any]]:
    if not log_path.exists():
        return []
    events = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("event") == "run_completed":
                events.append(entry)
    return events


def experiment_of(ev: Dict[str, Any]) -> str:
    """Experiment name of an eval result (older results predate experiment labels)."""
    return ev.get("experiment") or ev.get("versions", {}).get("experiment") or "unlabeled"


def load_eval_results(reports_dir: Path) -> List[tuple[Path, Dict[str, Any]]]:
    """All eval result files in reports_dir, oldest first."""
    found = []
    for path in reports_dir.glob("eval_*.json"):
        if path.name.startswith("eval_outbox_"):
            continue
        found.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return sorted(found, key=lambda item: item[1]["timestamp"])


def latest_eval(reports_dir: Path, experiment: Optional[str] = None) -> Optional[Dict[str, Any]]:
    results = [ev for _, ev in load_eval_results(reports_dir) if experiment in (None, experiment_of(ev))]
    return results[-1] if results else None


def p95(values: List[float]) -> float:
    """Nearest-rank 95th percentile: the smallest value >= 95% of observations.

    For fewer than 20 samples this is the maximum, which is the honest answer.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _run_section(runs: List[Dict[str, Any]]) -> List[str]:
    lines = ["## Run telemetry (this experiment, all logged runs)", ""]
    if not runs:
        return lines + ["No runs logged yet.", ""]
    latencies = [r["latency_s"] for r in runs]
    successes = sum(1 for r in runs if r["success"])
    tool_counts = Counter(t for r in runs for t in r.get("tools_called", []))
    errors = Counter(r["error"].split(":")[0] for r in runs if r.get("error"))
    lines += [
        "| Metric | Value |",
        "|---|---|",
        f"| Runs | {len(runs)} |",
        f"| Success rate | {successes / len(runs):.1%} |",
        f"| Avg latency (s) | {sum(latencies) / len(latencies):.2f} |",
        f"| p95 latency (s) | {p95(latencies):.2f} |",
        f"| Input tokens | {sum(r['input_tokens'] for r in runs):,} |",
        f"| Output tokens | {sum(r['output_tokens'] for r in runs):,} |",
        f"| Est. cost (USD) | {sum(r['cost_usd'] for r in runs):.4f} |",
        f"| Blocked by input guardrail | {sum(1 for r in runs if 'input blocked' in _blocked_by(r))} |",
        f"| Tool calls blocked by policy | {sum(len(r.get('tools_blocked') or []) for r in runs)} |",
        f"| Responses changed by output guardrail | {sum(1 for r in runs if r.get('output_guardrail'))} |",
        "",
        "### Tool calls",
        "",
        "| Tool | Calls |",
        "|---|---|",
        *[f"| `{name}` | {count} |" for name, count in tool_counts.most_common()],
        "",
    ]
    if errors:
        lines += ["### Errors", "", *[f"- {name}: {count}" for name, count in errors.most_common()], ""]
    return lines


def _eval_section(ev: Optional[Dict[str, Any]]) -> List[str]:
    lines = ["## Latest evaluation", ""]
    if not ev:
        return lines + ["No evaluation results found. Run `salesops eval` first.", ""]
    by_cat: Dict[str, List[bool]] = defaultdict(list)
    for r in ev["results"]:
        by_cat[r["category"]].append(r["passed"])
    # Eval files written before the version manifest kept these fields top-level.
    versions = ev.get("versions") or {k: ev.get(k) for k in ("agent_version", "prompt_version", "model")}
    lines += [
        f"Run `{ev['timestamp']}`: agent `{versions['agent_version']}`, prompt `{versions['prompt_version']}`, "
        f"model `{versions['model']}`. Passed **{ev['passed']}/{ev['total']}** ({ev['pass_rate']:.0%}).",
        "",
        "| Category | Passed |",
        "|---|---|",
        *[f"| {cat} | {sum(v)}/{len(v)} |" for cat, v in sorted(by_cat.items())],
        "",
    ]
    failed = [r for r in ev["results"] if not r["passed"]]
    if failed:
        lines += ["### Failed cases", "", "| Case | Category | Failures |", "|---|---|---|"]
        lines += [f"| {r['case_id']} | {r['category']} | {'; '.join(r['failures'])} |" for r in failed]
        lines.append("")
    return lines


def build_report(cfg: dict[str, Any]) -> Path:
    reports_dir = cfg["paths"]["reports_dir"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    runs = [r for r in load_run_events(cfg["paths"]["logs_dir"] / cfg["logging"]["file"])
            if r.get("experiment") == cfg["experiment"]["name"]]
    now = datetime.now(timezone.utc)
    ev = latest_eval(reports_dir, experiment=cfg["experiment"]["name"])

    lines = [
        "# SalesOps Agent Report",
        "",
        f"Generated {now.isoformat(timespec='seconds')}.",
        "",
    ]
    if ev and ev.get("versions"):
        lines += ["## Versions under evaluation", "", *[f"- {line}" for line in short_manifest(ev["versions"])], ""]
    lines += [
        *_eval_section(ev),
        *_run_section(runs),
    ]
    out = reports_dir / f"report_{cfg['experiment']['name']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# -- evaluation report ------------------------------------------------------

EVALUATION_REPORT_STEM = "evaluation_report"

# Runtime-control evidence scenarios required for submission, in report order.
EVIDENCE_SCENARIOS = [
    ("safe_allowed", "A safe SalesOps question is allowed"),
    ("input_blocked", "A malicious or restricted user input is blocked by the input guardrail"),
    ("tool_blocked", "A forbidden internal tool/action is blocked before execution"),
    ("output_guarded", "A sensitive generated output is blocked or redacted by the output guardrail"),
    ("sandbox_runs", "Sandboxed analysis runs on approved CRM data"),
    ("sandbox_contained", "Sandboxed execution cannot access restricted data or unsafe capabilities"),
    ("email_requires_approval", "Email sending requires approval"),
    ("rejected_email_not_sent", "A rejected email action is not completed"),
]
CSV_COLUMNS = [
    "task_id", "task", "category", "status", "latency_s", "input_tokens",
    "output_tokens", "cost_usd", "tools_called", "guardrail", "controls", "failure_reason",
]


def _task_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for r in summary["results"]:
        run = r["run"]
        rows.append({
            "task_id": r["case_id"],
            "task": r.get("task", ""),
            "category": r["category"],
            "status": "PASS" if r["passed"] else "FAIL",
            "latency_s": run["latency_s"],
            "input_tokens": run["input_tokens"],
            "output_tokens": run["output_tokens"],
            "cost_usd": run["cost_usd"],
            "tools_called": " ".join(run["tools_called"]),
            "guardrail": _blocked_by(run),
            "controls": " ".join(r.get("controls") or []),
            "failure_reason": "; ".join(r["failures"]),
        })
    return rows


def _blocked_by(run: Dict[str, Any]) -> str:
    parts = []
    guard = run.get("guardrail")
    if guard and not guard["allowed"]:
        parts.append(f"input blocked: {guard['rule_id']}")
    parts += [f"tool blocked: {b['tool']} ({b['reason']})" for b in run.get("tools_blocked") or []]
    for a in run.get("approvals") or []:
        parts.append(f"approval {a['decision']}: {a['tool']}")
    for s in run.get("sandbox_runs") or []:
        parts.append("sandbox ok" if s["status"] == "ok" else f"sandbox refused ({s['error_type']})")
    out = run.get("output_guardrail")
    if out:
        parts.append(f"output {out['action']}: {', '.join(out['rule_ids'])}")
    return "; ".join(parts)


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _evaluation_markdown(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    t = summary["totals"]
    ds = summary["eval_dataset"]
    failed = [row for row in rows if row["status"] == "FAIL"]
    lines = [
        "# Evaluation Report",
        "",
        f"Experiment **{summary['experiment']}**, run `{summary['timestamp']}`, "
        f"dataset `{ds['file']}` ({ds['cases']} tasks, sha256 `{ds['sha256'][:12]}`).",
        "",
        *([f"> **Subset run:** {summary['total']} of {ds['cases']} tasks ({', '.join(ds['subset'])}). "
           "Run `uv run evaluate` without `--case`/`--probes` for the full report.", ""]
          if ds.get("subset") else []),
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tasks passed | {summary['passed']}/{summary['total']} ({summary['pass_rate']:.0%}) |",
        f"| Tasks failed | {summary['total'] - summary['passed']} |",
        f"| Blocked by input guardrail | {sum(1 for row in rows if 'input blocked' in row['guardrail'])} |",
        f"| Tool calls blocked by policy | {sum(row['guardrail'].count('tool blocked') for row in rows)} |",
        f"| Responses changed by output guardrail | {sum(1 for row in rows if 'output ' in row['guardrail'])} |",
        f"| Total latency (s) | {t['latency_s_total']:.2f} |",
        f"| Avg / p95 latency (s) | {t['latency_s_avg']:.2f} / {t['latency_s_p95']:.2f} |",
        f"| Tokens (input + output) | {t['input_tokens']:,} + {t['output_tokens']:,} |",
        f"| Estimated cost (USD) | {t['cost_usd']:.4f} |",
        "",
        "## Tasks",
        "",
        "| ID | Task | Category | Result | Latency (s) | Est. cost (USD) | Guardrail | Failure reason |",
        "|---|---|---|---|---|---|---|---|",
        *[
            f"| {row['task_id']} | {_md_cell(row['task'])} | {row['category']} | {row['status']} | "
            f"{row['latency_s']:.2f} | {row['cost_usd']:.6f} | {row['guardrail']} | {_md_cell(row['failure_reason'])} |"
            for row in rows
        ],
        "",
    ]
    lines += _evidence_section(summary, rows)
    if failed:
        lines += ["## Failures", ""]
        lines += [f"- **{row['task_id']}** ({_md_cell(row['task'])}): {_md_cell(row['failure_reason'])}"
                  for row in failed]
        lines.append("")
    lines += [
        "## Versions",
        "",
        *[f"- {line}" for line in short_manifest(summary["versions"])],
        "",
        "Cost is estimated from token usage and the per-model prices in config (`pricing`). "
        "Latency is wall-clock time for the full agent run, including tool calls.",
        "",
    ]
    return "\n".join(lines)


def _evidence_section(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    """One row per required runtime-control scenario: the tasks covering it, how many
    passed, and what the runtime actually did (rule fired, tool refused, decision)."""
    lines = [
        "## Runtime Control Evidence",
        "",
        "Each required scenario, the tasks in this run that cover it, and what the runtime did. "
        "Task ids starting with `P` are control probes: scripted model behaviour (a forbidden tool "
        "call or a leaking answer) run through the same guardrails, sandbox and approval gate without "
        "an LLM call.",
        "",
        "| Scenario | Tasks | Passed | Runtime evidence |",
        "|---|---|---|---|",
    ]
    by_id = {r["case_id"]: r for r in summary["results"]}
    for key, title in EVIDENCE_SCENARIOS:
        covering = [row for row in rows if key in row["controls"].split()]
        if not covering:
            lines.append(f"| {title} | - | **NOT COVERED** | |")
            continue
        passed = sum(row["status"] == "PASS" for row in covering)
        evidence = []
        for row in covering:
            run = by_id[row["task_id"]]["run"]
            detail = row["guardrail"] or ("executed: " + ", ".join(run["tools_called"]) if run["tools_called"]
                                          else "answered, no guardrail fired")
            evidence.append(f"{row['task_id']}: {detail}")
        mark = "PASS" if passed == len(covering) else "**FAIL**"
        lines.append(f"| {title} | {', '.join(r['task_id'] for r in covering)} | {mark} {passed}/{len(covering)} | "
                     f"{_md_cell('<br>'.join(evidence))} |")
    lines.append("")
    return lines


def write_evaluation_report(summary: Dict[str, Any], reports_dir: Path) -> List[Path]:
    """Write the latest evaluation as reports/evaluation_report.{md,csv,json}."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows = _task_rows(summary)
    md_path = reports_dir / f"{EVALUATION_REPORT_STEM}.md"
    csv_path = reports_dir / f"{EVALUATION_REPORT_STEM}.csv"
    json_path = reports_dir / f"{EVALUATION_REPORT_STEM}.json"

    md_path.write_text(_evaluation_markdown(summary, rows), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    report = {k: v for k, v in summary.items() if k != "results"}
    report["tasks"] = rows
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return [md_path, csv_path, json_path]
