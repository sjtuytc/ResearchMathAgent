#!/usr/bin/env bash
# Solve app — DEV internal server (port 8011).
# NOT exposed publicly — the proxy routes /rmac/solve/ here.
set -euo pipefail

PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${RMA_SOLVE_DEV_PORT:-8011}"

cd "$ROOT"
source "$ROOT/scripts/ensure_webapp_deps.sh"

# Optional local secrets (gitignored), e.g. ANTHROPIC_API_KEY for subscription
# billing of the /api/solve smoke endpoint.
if [ -f "$ROOT/.env.local" ]; then set -a; . "$ROOT/.env.local"; set +a; fi

echo "[solve-dev] Solve app on 127.0.0.1:${PORT}"

while true; do
    echo "[solve-dev $(date '+%Y-%m-%d %H:%M:%S')] launching…"
    PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m uvicorn webapp.server:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        --reload \
        --reload-delay 0.5 || true
    echo "[solve-dev $(date '+%Y-%m-%d %H:%M:%S')] exited, restarting in 3s…"
    sleep 3
done
