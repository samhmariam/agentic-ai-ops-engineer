#!/usr/bin/env sh
set -e

echo "=== Running MCP server tests ==="
uv run pytest -v

echo ""
echo "All checks passed."
