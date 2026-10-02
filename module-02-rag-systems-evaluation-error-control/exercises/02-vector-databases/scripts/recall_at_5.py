"""Recall@5 against a balanced subset of the golden set.

Usage (from the starter root):
    PYTHONPATH=. uv run python scripts/recall_at_5.py
    # or: make recall

Picks the first 5 factual / 3 procedural / 2 conceptual / 2 comparative
questions from ``data/golden_set.csv`` (edge_case and off_topic are left
out: they test refusal, not retrieval), embeds each with
``embedder.embed_query``, retrieves the top 5 from the ``scikit_docs``
collection, and reports:

- recall@5 — any top-5 ``doc_id`` starts with any expected prefix
  ("hit-any" semantics, see the golden set's ``expected_doc_ids``).
- hit@1 — the top result is already a match. ``seeded.*`` chunks from
  ``make seed-difficulty`` are skipped so the number reflects the real
  corpus whether or not they have been seeded.

``run`` takes the embed and retrieve functions as arguments so
``scripts/recall_at_5_st.py`` measures the MiniLM collection with the
exact same subset and scoring.
"""

from __future__ import annotations

import csv
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from src.models import Source

GOLDEN = Path("data/golden_set.csv")
SUBSET_SIZE: dict[str, int] = {"factual": 5, "procedural": 3, "conceptual": 2, "comparative": 2}
TOP_K: int = 5
SEEDED_PREFIX: str = "seeded."
# text-embedding-3-small: $0.02 / 1M tokens; a short question is ~1k tokens at most.
OPENAI_COST_PER_QUERY: float = 2e-5


def pick_subset(rows: list[dict], sizes: dict[str, int] = SUBSET_SIZE) -> list[dict]:
    """Take the first ``sizes[query_type]`` rows of each query type, in file order."""
    remaining = dict(sizes)
    picked = []
    for row in rows:
        if remaining.get(row["query_type"], 0) > 0:
            picked.append(row)
            remaining[row["query_type"]] -= 1
    return picked


def load_subset(path: Path = GOLDEN) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return pick_subset(list(csv.DictReader(fh)))


def hit_any(returned_ids: list[str], expected_prefixes: list[str]) -> bool:
    return any(r.startswith(p) for r in returned_ids for p in expected_prefixes if p)


def top1_unseeded(returned_ids: list[str]) -> str | None:
    """First returned id that is not a ``seeded.*`` difficulty chunk."""
    return next((r for r in returned_ids if not r.startswith(SEEDED_PREFIX)), None)


def run(
    embed_query: Callable[[str], list[float]],
    retrieve: Callable[[list[float], int], list[Source]],
    label: str,
    cost_per_query: float = 0.0,
) -> dict:
    """Score the 12-question subset; print a per-question table and summary."""
    picked = load_subset()
    hits = hits1 = 0
    latencies: list[float] = []
    start = time.monotonic()
    print(f"== {label} ==")
    for i, row in enumerate(picked, 1):
        t0 = time.monotonic()
        returned = [s.doc_id for s in retrieve(embed_query(row["question"]), TOP_K)]
        latencies.append(time.monotonic() - t0)
        expected = [p for p in row["expected_doc_ids"].split("|") if p]
        is_hit = hit_any(returned, expected)
        top1 = top1_unseeded(returned)
        is_hit1 = top1 is not None and hit_any([top1], expected)
        hits += is_hit
        hits1 += is_hit1
        print(
            f"Q{i:>2} [{row['query_type']:<11}] {'HIT ' if is_hit else 'MISS'} "
            f"@1={'Y' if is_hit1 else 'N'} {row['question'][:70]}\n"
            f"      top1 -> {returned[0] if returned else '-'}"
        )
    n = len(picked)
    elapsed = time.monotonic() - start
    median_latency = statistics.median(latencies)
    print(f"\nrecall@5: {hits}/{n} = {hits / n:.2f}")
    print(f"hit@1 (excluding seeded.*): {hits1}/{n} = {hits1 / n:.2f}")
    print(
        f"runtime:  {elapsed:.1f}s ({n} queries, median {median_latency:.3f}s/query, "
        f"${n * cost_per_query:.5f})"
    )
    return {
        "label": label,
        "n": n,
        "recall_at_5": hits / n,
        "hit_at_1": hits1 / n,
        "median_latency_s": median_latency,
    }


def main() -> None:
    from src import embedder, store

    run(
        embedder.embed_query,
        lambda qv, k: store.query(qv, n_results=k),
        label="text-embedding-3-small -> scikit_docs",
        cost_per_query=OPENAI_COST_PER_QUERY,
    )


if __name__ == "__main__":
    main()
