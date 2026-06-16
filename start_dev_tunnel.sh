#!/usr/bin/env bash
# Expose the dev server (port 8001) publicly via serveo.net over SSH.
# No installation required — just SSH.
# Preferred subdomain: rma-dev  →  https://rma-dev.serveo.net
# If that subdomain is taken, serveo assigns a random one (printed in output).
set -euo pipefail

DEV_PORT="${RMA_DEV_PORT:-8001}"
SUBDOMAIN="${RMA_DEV_SUBDOMAIN:-rma-dev}"

echo "[dev-tunnel] Connecting to serveo.net..."
echo "[dev-tunnel] Your dev URL will appear below (look for 'Forwarding ...')."
echo "[dev-tunnel] Ctrl-C to stop the tunnel."

while true; do
    ssh -i ~/.ssh/serveo_key \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=no \
        -R "${SUBDOMAIN}:80:localhost:${DEV_PORT}" \
        serveo.net || true
    echo "[dev-tunnel $(date '+%Y-%m-%d %H:%M:%S')] tunnel dropped, reconnecting in 5s..."
    sleep 5
done
