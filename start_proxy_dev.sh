#!/usr/bin/env bash
# Reverse proxy — DEV.
# Listens on the public-facing port (8001) and routes:
#   /rmac/solve/... → localhost:8011 (solve app)
#   /rmac/filter/... → localhost:8012 (filter app)
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_PROXY_PORT:-8001}"
HOST="${RMA_HOST:-0.0.0.0}"
SOLVE_INTERNAL="${RMA_SOLVE_DEV_PORT:-8011}"
FILTER_INTERNAL="${RMA_FILTER_DEV_PORT:-8012}"

cd "$ROOT"

echo "[proxy-dev] Proxy on ${HOST}:${PORT}  →  solve:${SOLVE_INTERNAL}  filter:${FILTER_INTERNAL}"

while true; do
    echo "[proxy-dev $(date '+%Y-%m-%d %H:%M:%S')] launching…"
    PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
    RMAC_SOLVE_ORIGIN="http://127.0.0.1:${SOLVE_INTERNAL}" \
    RMAC_FILTER_ORIGIN="http://127.0.0.1:${FILTER_INTERNAL}" \
    "$PYTHON" -m uvicorn proxy_server:app \
        --host "$HOST" \
        --port "$PORT" \
        --reload \
        --reload-include "proxy_server.py" \
        --reload-delay 0.5 || true
    echo "[proxy-dev $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s…"
    sleep 3
done
