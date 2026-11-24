#!/usr/bin/env bash
# Starts the studio and opens it in the browser.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run ./install.sh first."; exit 1; }
PORT=$(grep -E '^STUDIO_PORT=' .env 2>/dev/null | cut -d= -f2); PORT=${PORT:-8765}
( sleep 2; (command -v open >/dev/null && open "http://127.0.0.1:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT") || true ) >/dev/null 2>&1 &
exec .venv/bin/python -m studio
