"""Enforce the forward-dependency rule across the src/ tree.

For every module ``src.X``, every ``import src.Y`` (or ``from src.Y ...``)
must satisfy ``RANK[Y] < RANK[X]`` — i.e. modules import only from
*earlier* modules in the curriculum order. This keeps each course module
readable without forward references to packages the learner hasn't seen yet.

One documented exception: ``src.gateway.app`` imports
``src.optimization.routes`` to mount the streaming endpoint. This is
allowed because ``app.include_router`` is the operator's seam — the
FastAPI app has to know about every router it serves — and the API
needed the streaming endpoint to live alongside ``/query`` even though
forward-dependency would put it elsewhere.
"""

import ast
from pathlib import Path

# Module ranks. Shared infra ('config', 'models', 'pricing') sits at 0;
# anything can import from them. Higher ranks come from the plan's
# Module dependency graph.
RANK: dict[str, int] = {
    "config": 0,
    "models": 0,
    "pricing": 0,
    "vectordb": 2,
    "rag": 3,
    "tracing": 4,
    "evaluation": 5,
    "cost": 6,
    "cache": 7,
    "gateway": 8,
    "guardrails": 9,
    "ingestion": 10,
    "optimization": 11,
}

# (consumer_dotted_path, target_package) — explicitly allowed exceptions.
#
# Pattern: a wrapper module that lives in a package the curriculum teaches
# *before* the package it wraps. Documented in the REQ archives.
ALLOWED_EXCEPTIONS: set[tuple[str, str]] = {
    # gateway.app mounts the streaming router via include_router. The
    # streaming endpoint lives in the optimization package (taught later
    # than the gateway) per the forward-dependency rule, but the FastAPI
    # app has to know about it to mount it. This is a wiring concern,
    # not a code-dependency concern.
    ("src.gateway.app", "optimization"),
    # gateway.app starts the inbox watcher in its lifespan. The watcher
    # must run in the SAME process as /query because chromadb's
    # PersistentClient caches the HNSW segment per process — a watcher
    # spawned separately (e.g. via `make watch`) updates SQLite on disk
    # but the server's cached segment goes stale until restart. The
    # ingestion package is taught later than gateway per the curriculum
    # order, but the process-boundary constraint forces the wiring here.
    ("src.gateway.app", "ingestion"),
    # cache.wrapper provides cached_route_query, which wraps
    # gateway.route_query. The cache package is taught earlier than the
    # gateway in the curriculum, but the wrapper has to live in the
    # cache package because that's where its purpose lives. Operators
    # opt in via cache.cached_route_query.
    ("src.cache.wrapper", "gateway"),
    # Ship-readiness security review (2026-04-24, finding F-01): the
    # production HTTP endpoint composes input guards, semantic cache,
    # gateway routing, and output guards. The composition belongs at
    # the HTTP boundary so the shipped starter exercises every layer
    # the course teaches. The gateway can still be read in isolation
    # via src.gateway.router and the standalone wrappers
    # (src.guardrails.wrapper.guarded_route_query,
    # src.cache.wrapper.cached_route_query) which the curriculum
    # introduces in their own modules.
    ("src.gateway.routes", "guardrails"),
    # Same rationale for the streaming endpoint: input guards run
    # before the stream opens. Output guards over streamed tokens are
    # deferred to a follow-up exercise.
    ("src.optimization.routes", "guardrails"),
}

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


def _module_to_package(module_name: str) -> str:
    """``src.gateway.routes`` -> ``gateway``."""
    parts = module_name.split(".")
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    return parts[0]


def _imports_from(file_path: Path) -> set[str]:
    """Return the set of ``src.PKG`` modules imported by ``file_path``."""
    tree = ast.parse(file_path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    imports.add(alias.name)
    return imports


def _consumer_module(file_path: Path) -> str:
    """``src/gateway/app.py`` -> ``src.gateway.app``."""
    rel = file_path.relative_to(SRC_ROOT.parent)  # relative to project/starter
    return ".".join(rel.with_suffix("").parts)


def test_every_src_package_has_a_rank():
    packages = {p.name for p in SRC_ROOT.iterdir() if p.is_dir() and not p.name.startswith("__")}
    # Single-file modules at src root are rank 0
    single_files = {p.stem for p in SRC_ROOT.glob("*.py") if p.stem != "__init__"}

    for pkg in packages | single_files:
        assert pkg in RANK, f"No rank assigned for src/{pkg} — update RANK in this test"


def test_no_module_imports_from_a_higher_ranked_package():
    violations: list[str] = []

    for src_file in SRC_ROOT.rglob("*.py"):
        if src_file.name == "__init__.py":
            continue
        consumer_path = _consumer_module(src_file)
        consumer_pkg = _module_to_package(consumer_path)
        consumer_rank = RANK.get(consumer_pkg, 0)

        for imported in _imports_from(src_file):
            target_pkg = _module_to_package(imported)
            if target_pkg == consumer_pkg:
                continue  # intra-package imports are fine
            if target_pkg not in RANK:
                continue
            target_rank = RANK[target_pkg]
            if target_rank > consumer_rank:
                if (consumer_path, target_pkg) in ALLOWED_EXCEPTIONS:
                    continue
                violations.append(
                    f"{consumer_path} (rank {consumer_rank}) imports from "
                    f"src.{target_pkg} (rank {target_rank})"
                )

    assert not violations, "Forward-dependency violations:\n  - " + "\n  - ".join(violations)


def test_documented_exceptions_are_actually_used():
    """If we list an exception, the import must really exist in the code."""
    for consumer, target in ALLOWED_EXCEPTIONS:
        consumer_path = SRC_ROOT.parent / Path(consumer.replace(".", "/")).with_suffix(".py")
        assert consumer_path.exists(), f"Exception consumer {consumer} not found"
        imports = _imports_from(consumer_path)
        assert any(_module_to_package(i) == target for i in imports), (
            f"Documented exception {consumer} -> {target} is not actually imported "
            "anymore — clean up ALLOWED_EXCEPTIONS"
        )


def test_no_circular_imports():
    """Build a directed graph of cross-package imports; assert it's acyclic.

    Exception edges (documented above) are excluded from the graph because
    they're wiring/wrap-back concerns, not module-level cyclic dependencies.
    """
    excepted_edges = {
        (_module_to_package(consumer), target)
        for consumer, target in ALLOWED_EXCEPTIONS
    }

    edges: dict[str, set[str]] = {pkg: set() for pkg in RANK}
    for src_file in SRC_ROOT.rglob("*.py"):
        if src_file.name == "__init__.py":
            continue
        consumer_path = _consumer_module(src_file)
        consumer_pkg = _module_to_package(consumer_path)
        for imported in _imports_from(src_file):
            target_pkg = _module_to_package(imported)
            if target_pkg in RANK and target_pkg != consumer_pkg:
                if (consumer_path, target_pkg) in ALLOWED_EXCEPTIONS:
                    continue
                if (consumer_pkg, target_pkg) in excepted_edges:
                    continue
                edges.setdefault(consumer_pkg, set()).add(target_pkg)

    # Topological sort via DFS; raises if a back-edge is found.
    visited: set[str] = set()
    in_progress: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        assert node not in in_progress, (
            f"Cycle involving {node}; in-progress chain: {in_progress}"
        )
        in_progress.add(node)
        for neighbour in edges.get(node, ()):
            visit(neighbour)
        in_progress.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)
