"""CLI: ``make watch`` → ``uv run python scripts/start_watcher.py``.

Runs the file-watcher as a separate process. Handles SIGINT/SIGTERM
gracefully so Ctrl+C and ``docker stop`` shut down cleanly.
"""

import argparse
import logging
import signal
import sys
from pathlib import Path
from threading import Event

from src.ingestion import start_watcher

DEFAULT_INBOX = Path(__file__).resolve().parents[1] / "data" / "inbox"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Watch a directory for new product JSONs and auto-ingest them."
    )
    parser.add_argument(
        "--inbox",
        type=Path,
        default=DEFAULT_INBOX,
        help=f"Inbox directory (default: {DEFAULT_INBOX}).",
    )
    parser.add_argument(
        "--failed",
        type=Path,
        default=None,
        help="Directory for malformed files (default: <inbox>/failed/).",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=0.5,
        help="Seconds to wait for a file's size+mtime to stabilise (default: 0.5).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    stop_event = Event()

    def _shutdown(signum, _frame):
        logging.info("Received signal %s, stopping watcher...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    start_watcher(
        inbox_dir=args.inbox,
        failed_dir=args.failed,
        debounce_s=args.debounce,
        stop_event=stop_event,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
