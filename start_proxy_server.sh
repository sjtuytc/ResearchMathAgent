#!/usr/bin/env bash
# Reverse proxy — PROD.
# Listens on the public-facing port (8000).
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_PORT:-8000}"
HOST="${RMA_HOST:-0.0.0.0}"
SOLVE_INTERNAL="${RMA_SOLVE_PROD_PORT:-8010}"
FILTER_INTERNAL="${RMA_FILTER_PROD_PORT:-8013}"

cd "$ROOT"

echo "[proxy-prod] Proxy on ${HOST}:${PORT}  →  solve:${SOLVE_INTERNAL}  filter:${FILTER_INTERNAL}"

while true; do
    echo "[proxy-prod $(date '+%Y-%m-%d %H:%M:%S')] launching…"
    PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
    RMAC_SOLVE_ORIGIN="http://127.0.0.1:${SOLVE_INTERNAL}" \
    RMAC_FILTER_ORIGIN="http://127.0.0.1:${FILTER_INTERNAL}" \
    "$PYTHON" -m uvicorn proxy_server:app \
        --host "$HOST" \
        --port "$PORT" || true
    echo "[proxy-prod $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s…"
    sleep 3
done
