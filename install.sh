#!/usr/bin/env bash
# One-time setup for macOS/Linux: creates .venv, installs dependencies and Chromium.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11+ is required."; exit 1; }
command -v ffmpeg >/dev/null || { echo "FFmpeg is required: macOS 'brew install ffmpeg', Ubuntu 'sudo apt install ffmpeg'."; exit 1; }
ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles " || echo "WARNING: this FFmpeg has no libass; burned-in captions will fail."
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
[ -f .env ] || cp .env.example .env
echo "Installed. Start the studio with ./start.sh"
