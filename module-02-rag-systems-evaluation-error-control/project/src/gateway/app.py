"""FastAPI application factory.

Mounts:
- POST /query, GET /health (gateway routes)
- GET /cost-dashboard (from src.cost.dashboard)

Lifespan: starts the embedded Arize Phoenix tracer on startup and
flushes any pending spans on shutdown so events from the final
requests are not dropped.
"""

# --- Suppress noisy third-party startup warnings ----------------------------
# Each filter targets a known upstream issue we don't control. Filters run
# BEFORE any other imports so they apply during module load — including the
# lazy `import phoenix as px` triggered later by init_tracing().
#
# We deliberately do NOT blanket-suppress DeprecationWarning, because
# warnings about learners' own code should still surface during development.
import sys
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"phoenix(\..*)?")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"pydantic(\..*)?")  # phoenix's models trigger pydantic v2 json_encoders deprecation
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"strawberry(\..*)?")  # phoenix's GraphQL layer uses old strawberry API
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"alembic(\..*)?")  # phoenix's DB migrations
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"websockets(\..*)?")  # uvicorn imports legacy websockets
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"uvicorn(\..*)?")  # uvicorn's own internal deprecations
warnings.filterwarnings("ignore", category=ResourceWarning, module=r"tempfile")  # phoenix tempdir cleanup on shutdown
try:
    from sqlalchemy.exc import SAWarning as _SAWarning
    warnings.filterwarnings("ignore", category=_SAWarning)  # phoenix sqlite expression-index reflection
except ImportError:  # SQLAlchemy is a phoenix transitive dep; missing means tracing is disabled
    pass
# ---------------------------------------------------------------------------

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from src.cost.dashboard import router as cost_router
from src.gateway.routes import router as api_router
from src.ingestion import start_observer
from src.optimization.routes import router as streaming_router
from src.tracing import flush, init_tracing

logger = logging.getLogger(__name__)

# data/inbox lives at the project root next to data/chroma. Hardcoding the
# default here (rather than reading from Settings) matches the path used
# by scripts/start_watcher.py — no new env knob to document.
INBOX_DIR = Path("data/inbox")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — start tracing + the inbox watcher on entry, clean up on exit.

    Phoenix's embedded mode launches the in-process UI here; the
    matching ``flush()`` on shutdown forces any queued spans to send
    before the process exits — without it, in-flight traces can be
    dropped. ``TRACING_BACKEND=none`` makes both calls no-ops.

    The inbox watcher is started in-process so that ``data/inbox/`` drops
    upsert into the SAME ``chromadb.PersistentClient`` the ``/query``
    route reads from. Running the watcher as a separate process (e.g. via
    ``make watch`` alongside ``make serve``) writes to the shared on-disk
    store but leaves the server's in-memory HNSW segment stale —
    chromadb's PersistentClient has no cross-process cache invalidation.
    """
    init_tracing()
    # Surface the watcher's `Ingested ...` and `Quarantined ...` lines in the
    # FastAPI logs. uvicorn attaches handlers to its own named loggers but
    # leaves the root logger empty, so an `INFO` record propagated up from
    # `src.ingestion.watcher` finds no handler and is dropped — only the
    # WARN-level `Quarantined` line surfaces (because the watcher emits that
    # one through `logger.warning(...)` which is at-level for root's default
    # of WARNING, but still goes nowhere without a handler... actually it
    # surfaces because uvicorn's `ERROR` handler picks up WARN records from
    # the propagation chain). Either way, the INFO records get lost.
    #
    # Standalone `make watch` already does this via
    # `logging.basicConfig(level="INFO")` in `scripts/start_watcher.py`;
    # mirror it for the in-process variant. Attach a StreamHandler directly
    # to the watcher logger so we don't depend on root's handler chain.
    #
    # Pin the handler to ``sys.stdout`` (default would be ``sys.stderr``).
    # ``make serve`` writes structlog DEBUG output to stdout, so a learner
    # tailing only stdout would otherwise miss the ``Ingested`` lines and
    # think the watcher was broken. Co-locating both streams on stdout
    # gives a single chronological log.
    _watcher_logger = logging.getLogger("src.ingestion.watcher")
    _watcher_logger.setLevel(logging.INFO)
    if not _watcher_logger.handlers:
        _h = logging.StreamHandler(sys.stdout)
        _h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        _watcher_logger.addHandler(_h)
    # NOTE: don't set propagate=False — pytest's caplog fixture depends on
    # propagation to capture records. A future uvicorn change that attaches
    # a handler to root could cause duplicate emission here; that's an
    # acceptable trade for keeping the test fixtures working.
    observer = start_observer(INBOX_DIR)
    try:
        yield
    finally:
        observer.stop()
        observer.join()
        logger.info("Inbox watcher stopped")
        flush()


def create_app() -> FastAPI:
    """Build and return the FastAPI app with every router mounted.

    Three routers are mounted from three different packages — each one
    owns the routes for its course module:

    - ``src/gateway/routes.py`` → ``POST /query``, ``GET /health``
    - ``src/cost/dashboard.py`` → ``GET /cost-dashboard``
    - ``src/optimization/routes.py`` → ``POST /query/stream``

    Mounting routers from later-curriculum packages (here: optimization)
    is the documented exception in the forward-dependency fitness
    function (``tests/integration/test_dependency_graph.py``). The app is
    a wiring layer, so it's allowed to know about every package.
    """
    app = FastAPI(title="LLM FAQ Service", lifespan=lifespan)
    app.include_router(api_router)
    app.include_router(cost_router)
    app.include_router(streaming_router)
    return app


app = create_app()
