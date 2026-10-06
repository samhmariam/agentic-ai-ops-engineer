"""Harvest a near-complete WRITEUP draft from a live capstone.

Runs every rubric §1–§11 verification end-to-end and dumps the
captured evidence into `WRITEUP-draft.md` at the starter root, plus
binary artifacts (the cost-dashboard HTML) under
`WRITEUP-evidence/`. The four sections that need genuine learner
judgment (§5 threshold proposal, §7 latency analysis, §9 scale
discussion, plus §1's choice of "your new product") get
`<!-- TODO: learner — ... -->` placeholders.

Per-section robustness: each section is wrapped in try/except so a
single failure (e.g. one helper missing or one transient timeout)
doesn't kill the whole run. Sections that depend on a shipped helper
emit a `(REQ-X not yet shipped — see INSTRUCTIONS Task X)` marker.

Usage:
    make serve              # in another terminal
    make harvest-evidence   # ~5–15 min wall clock; writes WRITEUP-draft.md
    uv run python scripts/harvest_evidence.py --skip-slow   # skip §2 sweep
"""

import argparse
import io
import json
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import httpx

HEALTH_URL = "http://localhost:8080/health"
QUERY_URL = "http://localhost:8080/query"
DASHBOARD_URL = "http://localhost:8080/cost-dashboard"

STARTER_ROOT = Path(__file__).resolve().parents[1]
DRAFT_PATH = STARTER_ROOT / "WRITEUP-draft.md"
EVIDENCE_DIR = STARTER_ROOT / "WRITEUP-evidence"
COST_LOG_PATH = STARTER_ROOT / "data" / "cost_log.jsonl"


# --- Pre-flight ---


def _preflight() -> None:
    try:
        httpx.get(HEALTH_URL, timeout=5.0).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: start `make serve` in another terminal first. "
            f"({exc.__class__.__name__})",
            file=sys.stderr,
        )
        sys.exit(2)


def _ensure_cost_log_seeded() -> None:
    """Run `seed_cost_log` if the log has fewer than 50 entries."""
    count = 0
    if COST_LOG_PATH.exists():
        with open(COST_LOG_PATH, "r", encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
    if count < 50:
        print(f"  Pre-flight: cost log has {count}/50 entries — seeding ...", file=sys.stderr)
        subprocess.run(
            ["uv", "run", "python", "scripts/seed_cost_log.py"],
            cwd=STARTER_ROOT, check=False,
        )


# --- HTTP helpers ---


def _post_query(question: str, *, top_k: int = 5) -> dict:
    r = httpx.post(QUERY_URL, json={"question": question, "top_k": top_k}, timeout=120.0)
    r.raise_for_status()
    return r.json()


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


# --- Section harvesters ---


def section_1_vector_db() -> str:
    """§1: confirm retrieval works for a question grounded in the corpus."""
    question = "What is the weight of the Selkirk AMPED S2?"
    response = _post_query(question)
    sources = response.get("sources", [])
    rows = "\n".join(
        f"| `{s.get('doc_id', '?')}` | {_md_escape(s.get('chunk_text', ''))[:90]} |"
        for s in sources[:3]
    ) or "| (no sources returned) |  |"
    return (
        f"**Question used:** `{question}`\n\n"
        f"**Top-3 retrieved sources:**\n\n"
        f"| doc_id | chunk excerpt |\n"
        f"|--------|---------------|\n{rows}\n\n"
        f"<!-- TODO: learner — repeat the curl with a question only one of "
        f"YOUR new products can answer, paste that response here, and confirm "
        f"the new product's doc_id appears in `sources`. -->"
    )


def section_2_topk_sweep(skip_slow: bool) -> str:
    if skip_slow:
        return (
            "_(`--skip-slow` set — re-run without that flag to populate this "
            "section, or paste the output of `make eval-topk-sweep` here.)_"
        )
    out = subprocess.run(
        ["uv", "run", "python", "scripts/eval_topk_sweep.py"],
        cwd=STARTER_ROOT, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return (
            f"_(eval-topk-sweep failed; see stderr in run log)_\n\n"
            f"```\n{out.stderr.strip()[-500:]}\n```"
        )
    return out.stdout.strip()


def section_3_gateway_routing() -> str:
    cases = [
        ("simple", "What is the weight of the Selkirk AMPED S2?"),
        ("complex", "Compare the Selkirk Vanguard Power Air and JOOLA Hyperion CFS 16 for tournament play."),
        ("borderline", "Is the Engage Pursuit MX a good first paddle for an intermediate player switching from tennis?"),
    ]
    rows = ["| Tier (intent) | Question | Model used |", "|---|---|---|"]
    for label, question in cases:
        try:
            response = _post_query(question)
            rows.append(f"| {label} | {_md_escape(question)} | `{response.get('model', '?')}` |")
        except Exception as exc:  # noqa: BLE001
            rows.append(f"| {label} | {_md_escape(question)} | ERROR: {exc.__class__.__name__} |")
    return "\n".join(rows)


def section_4_ingestion() -> str:
    """§4: capture inbox-template state + the bad.json parse error."""
    good = STARTER_ROOT / "data" / "inbox-templates" / "good.json"
    bad = STARTER_ROOT / "data" / "inbox-templates" / "bad.json"
    if not good.exists() or not bad.exists():
        return "_(REQ-026 not yet shipped — run manually per INSTRUCTIONS Task 4.)_"
    try:
        json.loads(bad.read_text())
        bad_error = "(unexpected: bad.json parsed without error)"
    except json.JSONDecodeError as exc:
        bad_error = f"{exc.__class__.__name__}: {exc.msg} (line {exc.lineno})"
    return (
        f"**Templates available:**\n\n"
        f"- `data/inbox-templates/good.json` — valid product, will be ingested by `make watch`.\n"
        f"- `data/inbox-templates/bad.json` — invalid: missing `price` field AND a trailing comma.\n\n"
        f"**Verification of bad.json failure mode** (parse-time):\n\n"
        f"```\n{bad_error}\n```\n\n"
        f"<!-- TODO: learner — run `make watch` in one terminal, then "
        f"`cp data/inbox-templates/good.json data/inbox/` and "
        f"`cp data/inbox-templates/bad.json data/inbox/`. Paste the watcher's "
        f"`.error.txt` content for bad.json + a curl confirming the good "
        f"product was ingested. -->"
    )


def section_5_eval_threshold() -> str:
    """§5: aggregate metrics + threshold-proposal placeholder."""
    out = subprocess.run(
        ["uv", "run", "python", "scripts/run_eval.py", "--limit", "10"],
        cwd=STARTER_ROOT, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return f"_(make eval failed)_\n\n```\n{out.stderr.strip()[-500:]}\n```"
    aggregate = "\n".join(
        line for line in out.stdout.splitlines()
        if any(k in line for k in ("faithfulness", "answer_relevancy", "context_recall", "context_precision"))
    ) or out.stdout.strip()
    return (
        f"**Aggregate metrics (subset of golden set):**\n\n"
        f"```\n{aggregate}\n```\n\n"
        f"<!-- TODO: learner — propose a regression threshold for one metric. "
        f"Cite the median + a tail percentile from your full `make eval` "
        f"output, justify the cutoff against that distribution, state what a "
        f"violation triggers. See the worked example in INSTRUCTIONS.md "
        f"Task 5 for shape. -->"
    )


def section_6_guardrails() -> str:
    return (
        "<!-- TODO: learner — Task 6 asks you to add ≥3 new injection "
        "patterns to `INJECTION_PATTERNS` in `src/guardrails/input_guards.py` "
        "(or one new sensitive-data type to `PII_PATTERNS` + "
        "`PII_REDACTIONS`). For each new pattern, paste two `POST /query` "
        "outputs: one whose response sets `blocked_by` to your new pattern, "
        "and one legitimate question whose response has `blocked_by: null`. "
        "See INSTRUCTIONS.md Task 6 for the curl shape. -->"
    )


def section_7_tracing() -> str:
    out = subprocess.run(
        ["uv", "run", "python", "scripts/seed_traces.py"],
        cwd=STARTER_ROOT, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return (
            f"_(REQ-024 seed-traces failed — run manually per INSTRUCTIONS Task 7.)_\n\n"
            f"```\n{out.stderr.strip()[-500:]}\n```"
        )
    return (
        f"{out.stdout.strip()}\n\n"
        f"<!-- TODO: learner — write 1–2 paragraphs on WHY this step is the "
        f"slowest. Reference what it does (model inference vs. I/O vs. "
        f"network), what the per-call latency floor is on your hardware, and "
        f"whether the answer would change at higher request volume. -->"
    )


def section_8_cost_dashboard() -> str:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_path = EVIDENCE_DIR / "cost-dashboard.html"
    r = httpx.get(DASHBOARD_URL, timeout=10.0)
    r.raise_for_status()
    dashboard_path.write_text(r.text)
    line_count = sum(1 for _ in COST_LOG_PATH.open()) if COST_LOG_PATH.exists() else 0
    return (
        f"**Cost log size:** `{line_count}` entries (rubric requires ≥50).\n\n"
        f"**Dashboard HTML saved to:** `WRITEUP-evidence/cost-dashboard.html` "
        f"(open in a browser for screenshot, or paste-as-`<details>` block).\n"
    )


def section_9_cost_savings() -> str:
    out = subprocess.run(
        ["uv", "run", "python", "scripts/cost_report.py"],
        cwd=STARTER_ROOT, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return f"_(cost_report failed)_\n\n```\n{out.stderr.strip()[-500:]}\n```"
    return (
        f"**`scripts/cost_report.py` output:**\n\n"
        f"```\n{out.stdout.strip()}\n```\n\n"
        f"<!-- TODO: learner — project monthly cost at higher request volume "
        f"(e.g., 10,000 queries/day). Discuss what changes at scale: do the "
        f"savings hold? Does the simple/complex mix shift? Is the bottleneck "
        f"still cost or does latency dominate? -->"
    )


def section_10_cache() -> str:
    """§10 (bonus): 6 paraphrased queries showing cache hit/miss."""
    paraphrases = [
        "What is the weight of the Selkirk AMPED S2?",
        "How much does the Selkirk AMPED S2 weigh?",
        "Tell me the weight of the Selkirk AMPED S2 paddle.",
        "Selkirk AMPED S2 paddle weight please?",
        "Selkirk AMPED S2 — what does it weigh?",
        "How heavy is the Selkirk AMPED S2 paddle in ounces?",
    ]
    rows = ["| # | Query | Cached? |", "|---|---|---|"]
    for i, question in enumerate(paraphrases, 1):
        try:
            response = _post_query(question)
            cached = "HIT" if response.get("cached") else "MISS"
        except Exception as exc:  # noqa: BLE001
            cached = f"ERROR ({exc.__class__.__name__})"
        rows.append(f"| {i} | {_md_escape(question)} | {cached} |")
    return "\n".join(rows)


def section_11_streaming() -> str:
    try:
        from src.optimization.streaming import compare_ttft
    except ImportError as exc:
        return f"_(compare_ttft import failed: {exc})_"

    questions = [
        "What is the weight of the Selkirk AMPED S2?",
        "Compare the Selkirk Vanguard Power Air and JOOLA Hyperion CFS 16.",
        "What does ThirdShotHub recommend for a beginner with arm fatigue?",
    ]
    rows = ["| # | Question | Blocking TTFT (ms) | Streaming TTFT (ms) | Improvement |",
            "|---|---|---|---|---|"]
    for i, question in enumerate(questions, 1):
        try:
            r = compare_ttft(question)
            rows.append(
                f"| {i} | {_md_escape(question)} | {r['blocking']['ttft_ms']:.0f} | "
                f"{r['streaming']['ttft_ms']:.0f} | {r['ttft_improvement_pct']:.1f}% |"
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(f"| {i} | {_md_escape(question)} | ERROR | — | {exc.__class__.__name__} |")
    return "\n".join(rows)


# --- Orchestration ---


SECTIONS: list[tuple[str, str, callable]] = [
    ("1", "Vector Database Populated", section_1_vector_db),
    ("3", "LLM Gateway With Tiered Routing", section_3_gateway_routing),
    ("4", "Automated Data Ingestion (file watcher)", section_4_ingestion),
    ("5", "Automated Evaluation Suite (RAGAS)", section_5_eval_threshold),
    ("6", "Input and Output Guardrails", section_6_guardrails),
    ("7", "Distributed Tracing (Phoenix)", section_7_tracing),
    ("8", "Cost Monitoring Dashboard", section_8_cost_dashboard),
    ("9", "Cost Savings Analysis", section_9_cost_savings),
    ("10", "Semantic Caching (bonus)", section_10_cache),
    ("11", "Latency Optimization via Streaming (bonus)", section_11_streaming),
]


def harvest(skip_slow: bool) -> tuple[str, list[tuple[str, str]]]:
    """Run all sections and return (markdown, list of (section_id, status))."""
    blocks: list[str] = [
        "# WRITEUP — Harvested Draft\n",
        "_Auto-generated by `make harvest-evidence`. Copy into `WRITEUP.md`, "
        "fill the `<!-- TODO: learner — ... -->` analysis blocks, then "
        "submit. Re-run anytime to refresh evidence._\n",
    ]
    statuses: list[tuple[str, str]] = []

    # §2 is special — uses the skip-slow flag.
    section_2 = ("2", "RAG Pipeline With Structured Output (top_k sweep)",
                 lambda: section_2_topk_sweep(skip_slow))

    plan: list[tuple[str, str, callable]] = [SECTIONS[0], section_2] + SECTIONS[1:]

    for sec_id, title, fn in plan:
        print(f"  §{sec_id}: {title} ...", file=sys.stderr)
        t0 = time.perf_counter()
        try:
            body = fn()
            status = f"ok ({time.perf_counter() - t0:.1f}s)"
        except Exception as exc:  # noqa: BLE001
            body = f"_(harvest failed: {exc.__class__.__name__}: {exc})_\n\n```\n{traceback.format_exc()[-500:]}\n```"
            status = f"FAILED: {exc.__class__.__name__}"
        blocks.append(f"\n## Deliverable {sec_id} — {title}\n\n{body}\n")
        statuses.append((sec_id, status))

    return "\n".join(blocks), statuses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Harvest a WRITEUP draft from a live capstone."
    )
    parser.add_argument(
        "--skip-slow", action="store_true",
        help="Skip §2 (eval-topk-sweep) — saves ~5–10 min for fast smoke runs.",
    )
    args = parser.parse_args(argv)

    _preflight()
    _ensure_cost_log_seeded()

    print(f"Harvesting evidence into {DRAFT_PATH} ...", file=sys.stderr)
    markdown, statuses = harvest(args.skip_slow)
    DRAFT_PATH.write_text(markdown)

    print("\n=== Summary ===", file=sys.stderr)
    for sec_id, status in statuses:
        print(f"  §{sec_id}: {status}", file=sys.stderr)

    failed = [(s, st) for s, st in statuses if st.startswith("FAILED")]
    if failed:
        print(f"\n{len(failed)} section(s) failed:", file=sys.stderr)
        for sec_id, st in failed:
            print(f"  §{sec_id}: {st}", file=sys.stderr)

    print(
        f"\nharvest complete — copy {DRAFT_PATH.name} to WRITEUP.md, fill in "
        f"the learner-analysis placeholders, and submit.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
