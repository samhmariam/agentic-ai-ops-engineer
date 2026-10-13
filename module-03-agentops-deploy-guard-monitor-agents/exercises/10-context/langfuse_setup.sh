#!/usr/bin/env sh
# Bring up a local Langfuse and wire its keys into this folder's .env.
#
# Clones the pinned Langfuse stack, starts it with a known project key (no UI
# step needed), waits until it is healthy, and writes the LANGFUSE_* lines into
# .env. Re-runnable: it skips the clone if it is already there.
#
#   sh langfuse_setup.sh           # start (keeps any existing traces)
#   sh langfuse_setup.sh --fresh   # wipe existing traces first, then start
#
# Use --fresh before recording so the UI has no old traces.
#
# Prefer Langfuse Cloud instead? Skip this script, paste your own keys into
# .env, and set LANGFUSE_HOST=https://us.cloud.langfuse.com.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LF_DIR="$DIR/langfuse"
HOST="http://localhost:3000"
PUBLIC_KEY="pk-lf-realthor0000000000000000"
SECRET_KEY="sk-lf-realthor0000000000000000"

FRESH=0
for arg in "$@"; do
    [ "$arg" = "--fresh" ] && FRESH=1
done

if [ ! -d "$LF_DIR" ]; then
    echo "Cloning Langfuse (v3.130.0)..."
    git clone --depth 1 --branch v3.130.0 https://github.com/langfuse/langfuse.git "$LF_DIR"
fi

if [ "$FRESH" = "1" ]; then
    echo "Wiping existing Langfuse data (--fresh)..."
    (cd "$LF_DIR" && docker compose down -v 2>/dev/null) || true
fi

# Known org/project/user + keys, created headlessly on first boot (no UI).
cat > "$LF_DIR/.env" <<EOF
LANGFUSE_INIT_ORG_ID=realthor
LANGFUSE_INIT_ORG_NAME=RealThor
LANGFUSE_INIT_PROJECT_ID=realthor
LANGFUSE_INIT_PROJECT_NAME=RealThor
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=$PUBLIC_KEY
LANGFUSE_INIT_PROJECT_SECRET_KEY=$SECRET_KEY
LANGFUSE_INIT_USER_EMAIL=demo@realthor.local
LANGFUSE_INIT_USER_PASSWORD=realthor-demo
LANGFUSE_INIT_USER_NAME=RealThor Demo
EOF

echo "Starting Langfuse..."
(cd "$LF_DIR" && docker compose up -d)

printf "Waiting for Langfuse at %s " "$HOST"
until curl -sf "$HOST/api/public/health" >/dev/null 2>&1; do
    printf "."
    sleep 5
done
echo " ready."

# Write the keys into this project's .env, preserving any non-Langfuse lines.
ENV="$DIR/.env"
[ -f "$ENV" ] || touch "$ENV"
grep -v '^LANGFUSE_' "$ENV" > "$ENV.tmp" 2>/dev/null || true
mv "$ENV.tmp" "$ENV"
cat >> "$ENV" <<EOF
LANGFUSE_PUBLIC_KEY=$PUBLIC_KEY
LANGFUSE_SECRET_KEY=$SECRET_KEY
LANGFUSE_HOST=$HOST
EOF

echo ""
echo "Langfuse is up at $HOST — keys written to .env."
echo "Stop it later with: (cd langfuse && docker compose down -v)"
