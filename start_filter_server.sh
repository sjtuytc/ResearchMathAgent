#!/usr/bin/env bash
# Filter app — PROD internal server (port 8013).
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_FILTER_PROD_PORT:-8013}"

cd "$ROOT"
source "$ROOT/scripts/ensure_webapp_deps.sh"

echo "[filter-prod] Filter app on 127.0.0.1:${PORT}"

while true; do
    echo "[filter-prod $(date '+%Y-%m-%d %H:%M:%S')] launching…"
    PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m uvicorn webapp_filter.server:app \
        --host 127.0.0.1 \
        --port "$PORT" || true
    echo "[filter-prod $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s…"
    sleep 3
done
