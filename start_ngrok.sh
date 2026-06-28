#!/usr/bin/env bash
# Start the ngrok tunnel for production.
# Restarts automatically if the tunnel drops.
# The reserved domain is NOT hardcoded — set NGROK_DOMAIN (e.g. in .env.local)
# to your ngrok reserved domain so rotating it never re-publishes a URL in git.
set -euo pipefail

# Pick up NGROK_DOMAIN from .env.local if present.
_here="$(cd "$(dirname "$0")" && pwd)"
[ -f "${_here}/.env.local" ] && { set -a; . "${_here}/.env.local"; set +a; }

NGROK=/projects/bhov/zzhao18/software/bin/ngrok
PROD_PORT="${RMA_PORT:-8000}"
DOMAIN="${NGROK_DOMAIN:?set NGROK_DOMAIN to your ngrok reserved domain (e.g. in .env.local)}"

echo "[ngrok] Exposing port ${PROD_PORT} as https://${DOMAIN}"

while true; do
    "$NGROK" http --domain="${DOMAIN}" "${PROD_PORT}" || true
    echo "[ngrok $(date '+%Y-%m-%d %H:%M:%S')] tunnel dropped, reconnecting in 5s..."
    sleep 5
done
