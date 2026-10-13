#!/usr/bin/env sh
set -e

echo "=== Running unit tests ==="
uv run pytest tests/test_config.py tests/test_tools.py tests/test_guardrails.py tests/test_sandbox.py tests/test_policies.py tests/test_monitor.py tests/test_replay.py tests/test_tracing.py tests/test_context.py tests/test_auth.py tests/test_sessions.py tests/test_interactive.py tests/test_mcp.py -v

echo ""
echo "=== Checking data integrity ==="
uv run pytest tests/test_data_integrity.py -v

echo ""
echo "=== Seeding application database (realthor.db) ==="
uv run python data_forge/seed_db.py

echo ""
echo "=== Running evaluation ==="
uv run python evaluation/run_eval.py

echo ""
echo "=== Building containers (mcp data service + realthor client) ==="
docker compose build

echo ""
echo "=== Deployed smoke: realthor image runs (ops command, no server needed) ==="
docker compose run --rm realthor report

echo ""
echo "All checks passed."
