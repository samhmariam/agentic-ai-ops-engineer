"""Capstone verification checklist runner.

Runs the automatable subset of the integration verification checklist
and prints what the operator must check manually (anything that needs a
running OpenAI key + Phoenix tracing).

Usage:
    uv run python scripts/verify_capstone.py
"""

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable


@dataclass
class Check:
    name: str
    runner: Callable[[], tuple[str, str]]  # returns (status, detail)


def _pytest_subset(label: str, *paths: str) -> tuple[str, str]:
    """Run a subset of pytest paths; return ('PASS'|'FAIL', summary)."""
    result = subprocess.run(
        ["uv", "run", "pytest", *paths, "-q", "--no-header"],
        capture_output=True,
        text=True,
    )
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)"
    status = "PASS" if result.returncode == 0 else "FAIL"
    return status, f"{label}: {line}"


def check_unit_tests() -> tuple[str, str]:
    return _pytest_subset("Unit tests", "tests/")


def check_dependency_graph() -> tuple[str, str]:
    return _pytest_subset("Forward-dependency graph", "tests/integration/test_dependency_graph.py")


def check_schema_completeness() -> tuple[str, str]:
    return _pytest_subset("QueryResponse schema", "tests/integration/test_schema_completeness.py")


def check_end_to_end_wired() -> tuple[str, str]:
    return _pytest_subset("Cross-package end-to-end", "tests/integration/test_end_to_end.py")


AUTOMATED_CHECKS: list[Check] = [
    Check("unit-tests-pass", check_unit_tests),
    Check("dependency-graph-forward-only", check_dependency_graph),
    Check("query-response-schema-complete", check_schema_completeness),
    Check("end-to-end-wiring", check_end_to_end_wired),
]


# Note: an "import each src.PKG in isolation" check would be ideal but
# can't run cleanly in CI — chromadb.PersistentClient writes to disk on
# construction, openai.OpenAI tries to connect on use, and Phoenix's
# launch_app() opens a port. Pytest works around this with conftest
# stubs. Operators can verify post-deploy: with services running, every
# `python -c 'import src.PKG'` should succeed.


MANUAL_CHECKS: list[str] = [
    "make load-data — data/chroma/ is populated; PersistentClient.get_or_create_collection('products').count() returns >0",
    "POST /query (simple) — returns response via gpt-4o-mini (check `model` field)",
    "POST /query (complex) — returns response via gpt-4o (check `model` field)",
    "data/cost_log.jsonl — appended after each query",
    "Phoenix tracing dashboard at http://localhost:6006 — trace appears for the request (check trace_id in response). If port 6006 isn't reachable, run `make show-traces` for a markdown export of the same trace data.",
    "make eval — RAGAS prints faithfulness/answer_relevancy/context_recall/context_precision",
    "Drop a malformed JSON in data/inbox/ — quarantined to data/inbox/failed/ with .error.txt",
    "Drop a valid product JSON in data/inbox/ — appears in Chroma within seconds",
    "POST /query/stream — receives SSE token events then a 'done' event",
    "make install-guardrails-models — DeBERTa + Presidio + zero-shot + NLI models cached",
    "guarded_route_query (or _llmguard) — injection input returns blocked_by; clean input passes",
    "cached_route_query — repeat query within TTL returns cached=true (verify entries via `chromadb.PersistentClient(path='data/chroma').get_or_create_collection('cache').count()`)",
]


def main() -> int:
    print("=" * 70)
    print("Capstone verification — automated checks")
    print("=" * 70)

    results: list[tuple[str, str, str]] = []
    for check in AUTOMATED_CHECKS:
        status, detail = check.runner()
        marker = "[+]" if status == "PASS" else "[X]"
        print(f"{marker} {check.name}")
        print(f"    {detail}")
        results.append((check.name, status, detail))

    print()
    print("=" * 70)
    print("Manual verification (requires running services + credentials)")
    print("=" * 70)
    for item in MANUAL_CHECKS:
        print(f"[ ] {item}")

    print()
    print("=" * 70)
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"Automated: {len(results) - len(failed)} passed, {len(failed)} failed")
    print(f"Manual: {len(MANUAL_CHECKS)} items to verify in a real environment")
    print("=" * 70)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
