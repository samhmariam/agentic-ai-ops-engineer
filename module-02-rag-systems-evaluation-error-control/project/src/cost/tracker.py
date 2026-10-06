"""Per-request cost log (append-only JSONL) and summarization helpers."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.config import settings
from src.models import TokenUsage
from src.pricing import compute_cost  # re-exported for callers that prefer this entry point

QueryType = Literal["simple", "complex", "hallucination_check"]


def _resolve_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else Path(settings.cost_log_path)


def log_request(
    model: str,
    usage: TokenUsage,
    cost_usd: float,
    query_type: QueryType,
    *,
    path: str | Path | None = None,
) -> dict:
    """Append one request record to the JSONL cost log and return it."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost_usd": cost_usd,
        "query_type": query_type,
    }
    log_path = _resolve_path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def load_log(path: str | Path | None = None) -> list[dict]:
    """Read all records from the JSONL cost log. Empty list if file is missing."""
    log_path = _resolve_path(path)
    if not log_path.exists():
        return []
    with open(log_path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize(records: list[dict]) -> dict:
    """Aggregate records into totals + per-model breakdown."""
    by_model: dict[str, dict] = {}
    for r in records:
        bucket = by_model.setdefault(
            r["model"], {"requests": 0, "cost_usd": 0.0}
        )
        bucket["requests"] += 1
        bucket["cost_usd"] += r["cost_usd"]
    for model, bucket in by_model.items():
        bucket["avg_cost_usd"] = (
            bucket["cost_usd"] / bucket["requests"] if bucket["requests"] else 0.0
        )

    return {
        "total_requests": len(records),
        "total_cost_usd": sum(r["cost_usd"] for r in records),
        "by_model": by_model,
    }


__all__ = ["log_request", "load_log", "summarize", "compute_cost", "QueryType"]
