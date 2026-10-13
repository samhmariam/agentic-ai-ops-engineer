"""Compare two evaluation results.

This is what makes versioning useful for evaluation: given a baseline and a
candidate eval result (each carrying its version manifest), report
  - which versioned components differ (prompt, config, tools, model, code),
  - whether both were scored on the same eval dataset,
  - metric deltas (pass rate, latency, tokens, cost),
  - per-case transitions: fixed (fail -> pass) and regressed (pass -> fail).

Results are referenced by file path or by experiment name (latest run of that
experiment). Output goes to reports/compare_<baseline>_vs_<candidate>_<ts>.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from salesops_agent.reporting import experiment_of, latest_eval

ABSENT = "—"


@dataclass
class Comparison:
    baseline: str
    candidate: str
    version_rows: List[Tuple[str, str, str]]          # (component, baseline, candidate)
    dataset_match: bool
    metric_rows: List[Tuple[str, str, str, str]]      # (metric, baseline, candidate, delta)
    case_rows: List[Tuple[str, str, str, str, str]]   # (case, category, baseline, candidate, change)
    regressions: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)


def resolve_eval(ref: str, reports_dir: Path) -> Dict[str, Any]:
    """An eval result by file path, or the latest result for an experiment name."""
    path = Path(ref)
    if path.suffix == ".json" and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    ev = latest_eval(reports_dir, experiment=ref)
    if ev is None:
        raise FileNotFoundError(f"No eval result file or experiment named {ref!r} in {reports_dir}")
    return ev


def flatten_versions(manifest: Dict[str, Any]) -> Dict[str, str]:
    flat = {
        "experiment": manifest.get("experiment", ABSENT),
        "agent": manifest.get("agent_version", ABSENT),
        "prompt": f"{manifest.get('prompt_version', ABSENT)} ({manifest.get('prompt_sha256', '')[:12]})",
        "config": f"schema v{manifest.get('config_schema_version', '?')} ({manifest.get('config_sha256', '')[:12]})",
        "data schema": str(manifest.get("data_schema_version", ABSENT)),
        "model": f"{manifest.get('model', ABSENT)} @ t={manifest.get('temperature', '?')}",
        "git": (manifest.get("git") or {}).get("commit") or ABSENT,
    }
    for name, version in (manifest.get("tools") or {}).items():
        flat[f"tool: {name}"] = version
    return flat


def _metrics(ev: Dict[str, Any]) -> Dict[str, float]:
    runs = [r["run"] for r in ev["results"]]
    n = len(runs) or 1
    return {
        "pass rate": ev["pass_rate"],
        "passed": ev["passed"],
        "avg latency (s)": sum(r["latency_s"] for r in runs) / n,
        "input tokens": sum(r["input_tokens"] for r in runs),
        "output tokens": sum(r["output_tokens"] for r in runs),
        "cost (USD)": sum(r["cost_usd"] for r in runs),
    }


def _fmt(metric: str, value: float) -> str:
    if metric == "pass rate":
        return f"{value:.0%}"
    if metric == "cost (USD)":
        return f"{value:.4f}"
    if metric == "avg latency (s)":
        return f"{value:.2f}"
    return f"{value:,.0f}"


def _delta(metric: str, base: float, cand: float) -> str:
    diff = cand - base
    if metric == "pass rate":
        return f"{diff * 100:+.0f} pts"
    if base:
        return f"{diff:+,.4g} ({diff / base:+.0%})"
    return f"{diff:+,.4g}"


def compare(base: Dict[str, Any], cand: Dict[str, Any]) -> Comparison:
    bv, cv = flatten_versions(base.get("versions", {})), flatten_versions(cand.get("versions", {}))
    version_rows = [(k, bv.get(k, ABSENT), cv.get(k, ABSENT)) for k in dict.fromkeys([*bv, *cv])]

    bm, cm = _metrics(base), _metrics(cand)
    metric_rows = [(m, _fmt(m, bm[m]), _fmt(m, cm[m]), _delta(m, bm[m], cm[m])) for m in bm]

    b_cases = {r["case_id"]: r for r in base["results"]}
    c_cases = {r["case_id"]: r for r in cand["results"]}
    case_rows, regressions, fixes = [], [], []
    for case_id in sorted(set(b_cases) | set(c_cases)):
        b, c = b_cases.get(case_id), c_cases.get(case_id)
        category = (c or b)["category"]
        b_status = ABSENT if b is None else ("PASS" if b["passed"] else "FAIL")
        c_status = ABSENT if c is None else ("PASS" if c["passed"] else "FAIL")
        if b and c and b["passed"] and not c["passed"]:
            change = "regressed: " + "; ".join(c["failures"])
            regressions.append(case_id)
        elif b and c and not b["passed"] and c["passed"]:
            change = "fixed"
            fixes.append(case_id)
        elif b is None or c is None:
            change = "only in " + ("candidate" if b is None else "baseline")
        else:
            change = ""
        case_rows.append((case_id, category, b_status, c_status, change))

    b_ds, c_ds = base.get("eval_dataset"), cand.get("eval_dataset")
    return Comparison(
        baseline=experiment_of(base) + f" @ {base['timestamp']}",
        candidate=experiment_of(cand) + f" @ {cand['timestamp']}",
        version_rows=version_rows,
        dataset_match=bool(b_ds and c_ds and b_ds["sha256"] == c_ds["sha256"] and b_ds["subset"] == c_ds["subset"]),
        metric_rows=metric_rows,
        case_rows=case_rows,
        regressions=regressions,
        fixes=fixes,
    )


def render_markdown(comp: Comparison) -> str:
    changed = [row for row in comp.version_rows if row[1] != row[2]]
    lines = [
        f"# Evaluation comparison: {comp.baseline} vs {comp.candidate}",
        "",
        f"**{len(comp.fixes)} fixed, {len(comp.regressions)} regressed.**"
        + (f" Regressions: {', '.join(comp.regressions)}." if comp.regressions else ""),
        "",
    ]
    if not comp.dataset_match:
        lines += [
            "> **Warning:** the two runs were not scored on the same eval dataset "
            "(different cases file or case subset). Deltas are not like-for-like.",
            "",
        ]
    lines += ["## What changed", "", "| Component | Baseline | Candidate |", "|---|---|---|"]
    lines += [f"| {k} | {b} | {c} |" for k, b, c in changed] or ["| (no version differences) | | |"]
    lines += ["", "## Metrics", "", "| Metric | Baseline | Candidate | Delta |", "|---|---|---|---|"]
    lines += [f"| {m} | {b} | {c} | {d} |" for m, b, c, d in comp.metric_rows]
    lines += ["", "## Cases", "", "| Case | Category | Baseline | Candidate | Change |", "|---|---|---|---|---|"]
    lines += [f"| {cid} | {cat} | {b} | {c} | {chg} |" for cid, cat, b, c, chg in comp.case_rows]
    lines += ["", "<details><summary>All versions</summary>", "",
              "| Component | Baseline | Candidate |", "|---|---|---|"]
    lines += [f"| {k} | {b} | {c} |" for k, b, c in comp.version_rows]
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def write_comparison(baseline_ref: str, candidate_ref: str, reports_dir: Path) -> Tuple[Path, Comparison]:
    base = resolve_eval(baseline_ref, reports_dir)
    cand = resolve_eval(candidate_ref, reports_dir)
    comp = compare(base, cand)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = reports_dir / f"compare_{experiment_of(base)}_vs_{experiment_of(cand)}_{stamp}.md"
    out.write_text(render_markdown(comp), encoding="utf-8")
    return out, comp
