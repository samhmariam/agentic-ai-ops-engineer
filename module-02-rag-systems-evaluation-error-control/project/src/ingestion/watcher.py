"""Watch ``data/inbox/`` for new product JSONs, ingest them into Chroma.

In the RAGOps module, this watcher replaces the cloud Lambda+S3 design
from earlier drafts — same idea (event-driven knowledge-base
maintenance), no AWS dependency.

Edge cases handled:
- Partial writes: ``_wait_for_stable`` polls until the file's size and
  mtime stop changing.
- Malformed JSON or schema violations: file moves to ``failed/`` and a
  sibling ``.error.txt`` records why.
- Duplicate ``product_id``: Chroma's ``upsert`` is idempotent on ID.

To require a new field on incoming product JSONs, add it to
``REQUIRED_FIELDS`` (and to ``FIELD_MAX_LENGTHS`` if it's a string with
a sensible cap). To raise or lower the file-size cap, edit
``MAX_FILE_BYTES``. The chunking strategy lives in
``src.vectordb.chunker.chunk_product`` — change that if a product
should produce more than one chunk.
"""

import json
import logging
import shutil
import time
from pathlib import Path
from threading import Event

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.vectordb import add, chunk_product, embed

logger = logging.getLogger(__name__)

REQUIRED_FIELDS: set[str] = {
    "product_id",
    "name",
    "category",
    "brand",
    "price",
    "description",
    "specifications",
    "care_instructions",
}

# File-size and per-field caps. Product JSONs are small in practice; these
# ceilings exist so a single hostile or accidental file can't OOM the
# watcher process or flood the embeddings API with multi-megabyte text.
MAX_FILE_BYTES = 256 * 1024  # 256 KB

FIELD_MAX_LENGTHS: dict[str, int] = {
    "product_id": 64,
    "name": 200,
    "category": 64,
    "brand": 64,
    "description": 4000,
    "care_instructions": 2000,
}


def validate_product(product: dict) -> str | None:
    """Return None if ``product`` matches the schema, else a reason string."""
    if not isinstance(product, dict):
        return "product is not a JSON object"
    missing = REQUIRED_FIELDS - set(product.keys())
    if missing:
        return f"missing required fields: {sorted(missing)}"
    if not isinstance(product["specifications"], dict):
        return "specifications must be an object"
    for field, limit in FIELD_MAX_LENGTHS.items():
        value = product.get(field)
        if isinstance(value, str) and len(value) > limit:
            return f"{field} exceeds {limit}-character limit ({len(value)} chars)"
    return None


def _wait_for_stable(
    path: Path, debounce_s: float = 0.5, timeout_s: float = 5.0
) -> None:
    """Poll until ``path`` size+mtime are unchanged across two reads."""
    deadline = time.monotonic() + timeout_s
    last: tuple[int, float] | None = None
    while time.monotonic() < deadline:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return
        current = (stat.st_size, stat.st_mtime)
        if last == current:
            return
        last = current
        time.sleep(debounce_s)


def _quarantine(path: Path, failed_dir: Path, reason: str) -> Path:
    """Move ``path`` to ``failed_dir/`` with a sibling ``.error.txt``."""
    failed_dir.mkdir(parents=True, exist_ok=True)
    destination = failed_dir / path.name
    shutil.move(str(path), destination)
    destination.with_suffix(destination.suffix + ".error.txt").write_text(reason)
    logger.warning("Quarantined %s: %s", path.name, reason)
    return destination


def ingest_file(
    path: Path,
    *,
    failed_dir: Path,
    debounce_s: float = 0.5,
) -> str | None:
    """Validate, chunk, embed, and upsert a single product JSON file.

    Returns the ingested ``product_id`` on success, or None on failure
    (the file is moved to ``failed_dir/`` and the reason logged).
    """
    if path.suffix != ".json":
        return None  # Editor swap files etc — silently skip

    _wait_for_stable(path, debounce_s=debounce_s)

    try:
        size = path.stat().st_size
    except FileNotFoundError:
        # Race: file deleted between event and stat; nothing to do.
        return None
    if size > MAX_FILE_BYTES:
        _quarantine(
            path,
            failed_dir,
            f"file exceeds {MAX_FILE_BYTES}-byte limit ({size} bytes)",
        )
        return None

    try:
        product = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        _quarantine(path, failed_dir, f"invalid JSON: {exc}")
        return None
    except FileNotFoundError:
        # Race: file deleted between stat and read; nothing to do.
        return None

    if reason := validate_product(product):
        _quarantine(path, failed_dir, reason)
        return None

    chunks = chunk_product(product)
    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    ids = [c["metadata"]["product_id"] for c in chunks]
    embeddings = embed(texts)
    add(documents=texts, embeddings=embeddings, metadatas=metadatas, ids=ids)

    logger.info("Ingested %s (%d chunk(s))", product["product_id"], len(chunks))
    return product["product_id"]


class IngestionHandler(FileSystemEventHandler):
    """Routes filesystem events to ``ingest_file``."""

    def __init__(self, failed_dir: Path, debounce_s: float = 0.5) -> None:
        super().__init__()
        self._failed_dir = failed_dir
        self._debounce_s = debounce_s

    def _handle(self, src_path: str) -> None:
        path = Path(src_path)
        try:
            ingest_file(
                path,
                failed_dir=self._failed_dir,
                debounce_s=self._debounce_s,
            )
        except Exception:
            logger.exception("Unhandled error ingesting %s", src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.dest_path)


def start_observer(
    inbox_dir: Path,
    *,
    failed_dir: Path | None = None,
    debounce_s: float = 0.5,
) -> Observer:
    """Start a watchdog ``Observer`` on ``inbox_dir`` and return it (non-blocking).

    Used by the FastAPI lifespan so the watcher runs in the same process
    as the ``/query`` route. Running both in one process is what keeps
    ``chromadb.PersistentClient``'s in-memory HNSW segment consistent —
    a separately-spawned watcher would update SQLite on disk but the
    server's cached segment wouldn't see new entries until restart.

    The caller is responsible for ``observer.stop()`` + ``observer.join()``
    on shutdown.
    """
    inbox_dir = Path(inbox_dir)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    failed_dir = Path(failed_dir) if failed_dir else inbox_dir / "failed"

    handler = IngestionHandler(failed_dir=failed_dir, debounce_s=debounce_s)
    observer = Observer()
    observer.schedule(handler, str(inbox_dir), recursive=False)
    observer.start()
    logger.info("Watching %s for new product JSONs", inbox_dir)
    return observer


def start_watcher(
    inbox_dir: Path,
    *,
    failed_dir: Path | None = None,
    debounce_s: float = 0.5,
    stop_event: Event | None = None,
) -> None:
    """Watch ``inbox_dir`` until ``stop_event`` is set (or KeyboardInterrupt).

    Thin blocking wrapper around :func:`start_observer` for the CLI in
    ``scripts/start_watcher.py``. Inside the FastAPI process, prefer
    ``start_observer`` directly so the lifespan owns the shutdown.
    """
    observer = start_observer(
        inbox_dir, failed_dir=failed_dir, debounce_s=debounce_s
    )
    stop_event = stop_event or Event()
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        logger.info("Watcher stopped")
