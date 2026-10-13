"""Report generation.

Combines run telemetry from logs/ (all `run_completed` events) with the latest
evaluation result from reports/ into a Markdown report at reports/report_<experiment>_<ts>.md.
"""

from __future__ import annotations

import json
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


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def _run_section(runs: List[Dict[str, Any]]) -> List[str]:
    lines = ["## Run telemetry", ""]
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
        f"| p95 latency (s) | {_p95(latencies):.2f} |",
        f"| Input tokens | {sum(r['input_tokens'] for r in runs):,} |",
        f"| Output tokens | {sum(r['output_tokens'] for r in runs):,} |",
        f"| Est. cost (USD) | {sum(r['cost_usd'] for r in runs):.4f} |",
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
    runs = load_run_events(cfg["paths"]["logs_dir"] / cfg["logging"]["file"])
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
