#!/usr/bin/env sh
set -e

echo "=== Running unit tests ==="
uv run pytest tests/test_config.py tests/test_tools.py tests/test_guardrails.py tests/test_sandbox.py tests/test_policies.py tests/test_monitor.py tests/test_replay.py tests/test_tracing.py tests/test_context.py tests/test_auth.py tests/test_sessions.py tests/test_interactive.py -v

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
echo "=== Building container ==="
docker compose build

echo ""
echo "=== Running deployed agent ==="
docker compose run --rm realthor analyze --region west --property-type apartment --bedrooms 2 --user analyst_001 --password realthor-dev

echo ""
echo "All checks passed."
