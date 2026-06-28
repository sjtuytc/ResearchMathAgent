#!/usr/bin/env bash
# Solve app — PROD internal server (port 8010).
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_SOLVE_PROD_PORT:-8010}"

cd "$ROOT"
source "$ROOT/scripts/ensure_webapp_deps.sh"

# Optional local secrets (gitignored), e.g. ANTHROPIC_API_KEY for subscription
# billing of the /api/solve smoke endpoint.
if [ -f "$ROOT/.env.local" ]; then set -a; . "$ROOT/.env.local"; set +a; fi

echo "[solve-prod] Solve app on 127.0.0.1:${PORT}"

while true; do
    echo "[solve-prod $(date '+%Y-%m-%d %H:%M:%S')] launching…"
    PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m uvicorn webapp.server:app \
        --host 127.0.0.1 \
        --port "$PORT" || true
    echo "[solve-prod $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s…"
    sleep 3
done
