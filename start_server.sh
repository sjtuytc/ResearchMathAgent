#!/usr/bin/env bash
# Production server watchdog.
# NO --reload: prod stays stable until you run deploy.sh.
# The outer loop restarts automatically on crash.
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_PORT:-8000}"
HOST="${RMA_HOST:-0.0.0.0}"

cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/scripts/ensure_webapp_deps.sh"

echo "[prod] ResearchMathAgent production server on ${HOST}:${PORT}"
echo "[prod] Run deploy.sh to apply code changes to production."

while true; do
    echo "[prod $(date '+%Y-%m-%d %H:%M:%S')] launching..."
    "$PYTHON" -m uvicorn webapp.server:app \
        --host "$HOST" \
        --port "$PORT" || true
    echo "[prod $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s..."
    sleep 3
done
