"""Structured JSON-lines logging.

Every log line is one JSON object with a timestamp, level, event name and any extra
fields passed via `log_event`. Logs go to logs/<logging.file>; reporting.py reads
the `run_completed` events back to build monitoring reports.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

LOGGER_NAME = "salesops_agent"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, default=str)


def setup_logging(cfg: dict[str, Any]) -> logging.Logger:
    """Configure the package logger to write JSON lines to the configured log file."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(cfg["logging"].get("level", "INFO"))
    logger.propagate = False

    log_path = cfg["paths"]["logs_dir"] / cfg["logging"]["file"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    already = any(
        isinstance(h, logging.FileHandler) and h.baseFilename == str(log_path.resolve())
        for h in logger.handlers
    )
    if not already:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})


_RUNS_LOCK = threading.Lock()


def write_run_record(cfg: dict[str, Any], record: Dict[str, Any]) -> Path:
    """Append one run summary as a JSON line to logs/<logging.runs_file> (thread-safe)."""
    path = cfg["paths"]["logs_dir"] / cfg["logging"]["runs_file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str)
    with _RUNS_LOCK, path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return path
