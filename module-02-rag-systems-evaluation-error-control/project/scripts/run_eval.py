"""CLI: ``make eval`` → ``uv run python scripts/run_eval.py``."""

import argparse
import json
import sys
from pathlib import Path

from src.evaluation import evaluate_pipeline, load_golden_set, summarize

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "data" / "golden_test_set.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation on the RAG pipeline.")
    parser.add_argument(
        "--golden",
        type=Path,
        default=GOLDEN_PATH,
        help=f"Golden test set CSV (default: {GOLDEN_PATH}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N questions (default: all).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON file to write per-row results to.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help=(
            "Cap RAGAS executor concurrency. Default lets RAGAS use 16. "
            "Set to 1 when running through a contended proxy (e.g. Vocareum "
            "from a local CPU-only host) — trades wall-clock for completeness "
            "by avoiding parallel-load timeouts that produce nan metric cells."
        ),
    )
    args = parser.parse_args(argv)

    golden = load_golden_set(args.golden)
    if args.limit is not None:
        golden = golden[: args.limit]

    print(f"Evaluating {len(golden)} questions...")
    result = evaluate_pipeline(golden, max_workers=args.max_workers)
    aggregate = summarize(result)

    print("\nAggregate metrics:")
    for metric, score in aggregate.items():
        print(f"  {metric}: {score:.3f}")

    if args.output:
        args.output.write_text(
            json.dumps(
                {"aggregate": aggregate, "rows": result.to_pandas().to_dict("records")},
                indent=2,
                default=str,
            )
        )
        print(f"\nWrote per-row results to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
