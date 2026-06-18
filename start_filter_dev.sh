#!/usr/bin/env bash
# Filter app — DEV internal server (port 8012).
# Lightweight, read-only, no agent runs.
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_FILTER_DEV_PORT:-8012}"

cd "$ROOT"
source "$ROOT/scripts/ensure_webapp_deps.sh"

echo "[filter-dev] Filter app on 127.0.0.1:${PORT}"

while true; do
    echo "[filter-dev $(date '+%Y-%m-%d %H:%M:%S')] launching…"
    PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m uvicorn webapp_filter.server:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        --reload \
        --reload-delay 0.5 || true
    echo "[filter-dev $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s…"
    sleep 3
done
