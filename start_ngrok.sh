#!/usr/bin/env bash
# Start the ngrok tunnel for production (fixed domain).
# Restarts automatically if the tunnel drops.
set -euo pipefail

NGROK=/projects/bhov/zzhao18/software/bin/ngrok
PROD_PORT="${RMA_PORT:-8000}"
DOMAIN="zipfile-legume-gaining.ngrok-free.dev"

echo "[ngrok] Exposing port ${PROD_PORT} as https://${DOMAIN}"

while true; do
    "$NGROK" http --domain="${DOMAIN}" "${PROD_PORT}" || true
    echo "[ngrok $(date '+%Y-%m-%d %H:%M:%S')] tunnel dropped, reconnecting in 5s..."
    sleep 5
done
