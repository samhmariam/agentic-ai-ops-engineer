#!/usr/bin/env sh
set -e

echo "=== Running unit tests ==="
uv run pytest tests/ -v

echo ""
echo "=== Running evaluation ==="
uv run python evaluation/run_eval.py

echo ""
echo "=== Building container ==="
docker compose build

echo ""
echo "=== Running deployed agent ==="
docker compose run --rm realthor analyze --region west --property-type apartment --bedrooms 2

echo ""
echo "All checks passed."
