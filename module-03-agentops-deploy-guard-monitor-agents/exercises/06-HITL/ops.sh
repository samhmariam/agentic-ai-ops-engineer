#!/usr/bin/env sh
set -e

echo "=== Running unit tests ==="
uv run pytest tests/test_config.py tests/test_tools.py tests/test_guardrails.py tests/test_sandbox.py tests/test_policies.py -v

echo ""
echo "=== Checking data integrity ==="
uv run pytest tests/test_data_integrity.py -v

echo ""
echo "=== Running evaluation ==="
uv run python evaluation/run_eval.py

echo ""
echo "=== Building container ==="
docker compose build

echo ""
echo "=== Running deployed agent ==="
docker compose run --rm realthor analyze --region west --property-type apartment --bedrooms 2 --user analyst_001

echo ""
echo "All checks passed."
