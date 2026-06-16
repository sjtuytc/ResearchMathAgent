#!/usr/bin/env bash
# Development server — hot-reloads on every code change.
# Runs on port 8001, exposed publicly via start_dev_tunnel.sh.
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_DEV_PORT:-8001}"
HOST="${RMA_HOST:-0.0.0.0}"

cd "$ROOT"

echo "[dev] ResearchMathAgent DEV server on ${HOST}:${PORT}"
echo "[dev] Edits to Python/HTML files are reflected immediately (--reload)."

while true; do
    echo "[dev $(date '+%Y-%m-%d %H:%M:%S')] launching..."
    "$PYTHON" -m uvicorn webapp.server:app \
        --host "$HOST" \
        --port "$PORT" \
        --reload \
        --reload-delay 0.5 || true
    echo "[dev $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s..."
    sleep 3
done
