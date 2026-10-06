"""Evaluation — RAGAS-based quality measurement for the RAG pipeline."""

from src.evaluation.run_eval import (
    DEFAULT_METRICS,
    build_eval_dataset,
    evaluate_pipeline,
    load_golden_set,
    summarize,
)

__all__ = [
    "DEFAULT_METRICS",
    "load_golden_set",
    "build_eval_dataset",
    "evaluate_pipeline",
    "summarize",
]
