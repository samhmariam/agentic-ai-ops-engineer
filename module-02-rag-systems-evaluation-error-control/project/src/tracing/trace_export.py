"""Trace export rendering helpers (used by ``scripts/show_traces.py``).

The CLI script is a thin shell that connects to ``phoenix.Client`` and
delegates rendering to the functions in this module — so the rendering
logic stays unit-testable without spinning up a real Phoenix server.

Two output formats are supported: a markdown summary table grouped by
trace ID (the rubric §7 evidence path when the Phoenix UI port isn't
reachable) and JSON for programmatic consumption.
"""

import json
import math
from typing import Any


def _safe_int(value: Any) -> int:
    """Coerce a possibly-NaN/None pandas scalar to int. Defaults to 0.

    Phoenix attaches token counts only to LLM spans; retriever, embedding,
    and the rag_query root often have NaN here. ``int(NaN)`` raises, and
    ``NaN or 0`` doesn't short-circuit (NaN is truthy), so guard explicitly.
    """
    if value is None:
        return 0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    if math.isnan(f):
        return 0
    return int(f)


def summarize_traces(df: Any, last_n: int) -> list[dict]:
    """Group spans by trace_id, return one summary dict per trace.

    Each dict carries the rubric §7-relevant fields: trace_id (truncated
    for display), question, model, latency_ms, prompt/completion tokens,
    and the slowest child span name + duration.
    """
    if df is None or len(df) == 0:
        return []

    summaries: list[dict] = []
    for trace_id, group in df.groupby("context.trace_id"):
        root = group[group["name"] == "rag_query"]
        if len(root) == 0:
            root = group[group["parent_id"].isna()]
        if len(root) == 0:
            continue
        root_row = root.iloc[0]

        children = group[group["name"] != "rag_query"]
        if len(children) > 0:
            children = children.copy()
            children["_dur_ms"] = (
                (children["end_time"] - children["start_time"]).dt.total_seconds()
                * 1000
            )
            slowest = children.loc[children["_dur_ms"].idxmax()]
            slowest_name = str(slowest["name"])
            slowest_ms = round(float(slowest["_dur_ms"]), 1)
        else:
            slowest_name = "—"
            slowest_ms = 0.0

        # Phoenix flattens span attributes with namespaced keys like
        # `attributes.rag.<key>` into a single dict-valued column
        # `attributes.rag` — NOT into one flat column per nested key. So
        # `row["attributes.rag.latency_ms"]` is a missing-column read
        # that silently returns the fallback. The values live inside the
        # dict at `row["attributes.rag"]`.
        rag_attrs = root_row.get("attributes.rag") or {}
        if not isinstance(rag_attrs, dict):  # NaN-as-float guard
            rag_attrs = {}

        # Token counts are set on the `rag_generation` child span (see
        # src/tracing/phoenix_backend.py), not on the rag_query root.
        # Pull them from that child if present; otherwise zero.
        gen = group[group["name"] == "rag_generation"]
        if len(gen) > 0:
            gen_row = gen.iloc[0]
            prompt_tok = _safe_int(gen_row.get("attributes.llm.token_count.prompt", 0))
            completion_tok = _safe_int(gen_row.get("attributes.llm.token_count.completion", 0))
        else:
            prompt_tok = 0
            completion_tok = 0

        summaries.append(
            {
                "trace_id": str(trace_id)[:8],
                "question": str(
                    root_row.get("attributes.input.value", "—")
                )[:80],
                "model": str(rag_attrs.get("model", "—")),
                "latency_ms": round(
                    float(rag_attrs.get("latency_ms", 0) or 0), 1
                ),
                "prompt_tokens": prompt_tok,
                "completion_tokens": completion_tok,
                "slowest_span": slowest_name,
                "slowest_ms": slowest_ms,
                "start_time": str(root_row.get("start_time", "")),
            }
        )

    summaries.sort(key=lambda s: s["start_time"], reverse=True)
    return summaries[:last_n]


def render_markdown(summaries: list[dict], total: int) -> str:
    """Render the per-trace summary table as markdown."""
    if not summaries:
        return (
            "# Phoenix Trace Export\n\n"
            "No traces found yet — run a few queries via `POST /query`.\n"
        )

    lines = [
        "# Phoenix Trace Export",
        "",
        f"{total} trace(s) captured. Showing the most recent {len(summaries)}.",
        "",
        (
            "| # | Trace ID | Question | Model | Latency (ms) | "
            "Prompt tok | Compl. tok | Slowest child | Slowest (ms) |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(summaries, 1):
        lines.append(
            f"| {i} | `{s['trace_id']}` | {s['question']} | "
            f"{s['model']} | {s['latency_ms']} | "
            f"{s['prompt_tokens']} | {s['completion_tokens']} | "
            f"{s['slowest_span']} | {s['slowest_ms']} |"
        )
    return "\n".join(lines) + "\n"


def render_json(summaries: list[dict]) -> str:
    """Serialize summaries as pretty-printed JSON."""
    return json.dumps(summaries, indent=2, default=str)
